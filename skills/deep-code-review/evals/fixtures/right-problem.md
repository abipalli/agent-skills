# PR context

Title: Prevent duplicate webhook delivery

Problem statement: Providers retry the same webhook when our acknowledgment is
delayed. The same event can therefore be queued and delivered to customers more
than once. Customers have reported duplicate invoice notifications.

Production context:

- The API runs four replicas behind a load balancer.
- Any retry may reach a different replica.
- Replicas are restarted independently during deploys.
- The queue and delivery database are shared by all replicas.
- Neither the queue nor the delivery table currently has a unique event key.

# Diff

```diff
diff --git a/src/webhooks.rs b/src/webhooks.rs
index 4d1f2af..a18fcb3 100644
--- a/src/webhooks.rs
+++ b/src/webhooks.rs
@@ -1,11 +1,31 @@
+use std::collections::HashMap;
+use std::sync::Mutex;
+use std::time::{Duration, Instant};
+
 pub struct WebhookHandler {
     queue: DeliveryQueue,
+    recently_seen: Mutex<HashMap<String, Instant>>,
 }
 
 impl WebhookHandler {
     pub fn new(queue: DeliveryQueue) -> Self {
-        Self { queue }
+        Self {
+            queue,
+            recently_seen: Mutex::new(HashMap::new()),
+        }
     }
 
     pub async fn accept(&self, event: WebhookEvent) -> Result<(), WebhookError> {
+        let mut seen = self.recently_seen.lock().expect("recently_seen poisoned");
+        seen.retain(|_, observed_at| observed_at.elapsed() < Duration::from_secs(300));
+
+        if seen.contains_key(&event.id) {
+            return Ok(());
+        }
+
+        seen.insert(event.id.clone(), Instant::now());
+        drop(seen);
+
         self.queue.enqueue(event).await
     }
 }
```
