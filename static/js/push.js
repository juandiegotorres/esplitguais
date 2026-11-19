// Activar o desactivar las notificaciones push en este dispositivo (Mi cuenta).
// Se carga antes que Alpine para que el componente esté registrado en "alpine:init".
// En iPhone solo existe PushManager con la app instalada en la pantalla de inicio, y el
// permiso solo se puede pedir desde un toque: por eso es un botón y no un aviso automático.
document.addEventListener("alpine:init", () => {
  function keyBytes(base64url) {
    const base64 = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  }

  window.Alpine.data("pushToggle", () => ({
    // loading | unsupported | denied | off | on
    state: "loading",
    busy: false,
    error: "",

    async init() {
      if (!("serviceWorker" in navigator && "PushManager" in window && "Notification" in window)) {
        this.state = "unsupported";
        return;
      }
      if (Notification.permission === "denied") {
        this.state = "denied";
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      this.state = subscription && Notification.permission === "granted" ? "on" : "off";
      // Reenviarla repara el caso en que el servidor la borró (o el dispositivo cambió de usuario).
      if (this.state === "on") this.post("subscribe", subscription).catch(() => {});
    },

    async post(action, subscription) {
      const response = await fetch(this.$root.dataset[action], {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": this.$root.dataset.csrf },
        body: JSON.stringify(subscription),
        credentials: "same-origin",
      });
      if (response.status !== 204) throw new Error(`HTTP ${response.status}`);
    },

    async enable() {
      this.busy = true;
      this.error = "";
      try {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") {
          this.state = permission === "denied" ? "denied" : "off";
          return;
        }
        const registration = await navigator.serviceWorker.ready;
        const subscription =
          (await registration.pushManager.getSubscription()) ||
          (await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: keyBytes(this.$root.dataset.key),
          }));
        await this.post("subscribe", subscription);
        this.state = "on";
      } catch (error) {
        console.warn("No se pudieron activar las notificaciones:", error);
        this.error = "No se pudieron activar. Probá de nuevo en un rato.";
      } finally {
        this.busy = false;
      }
    },

    async disable() {
      this.busy = true;
      this.error = "";
      try {
        const registration = await navigator.serviceWorker.ready;
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
          await this.post("unsubscribe", { endpoint: subscription.endpoint });
          await subscription.unsubscribe();
        }
        this.state = "off";
      } catch (error) {
        console.warn("No se pudieron desactivar las notificaciones:", error);
        this.error = "No se pudieron desactivar. Probá de nuevo en un rato.";
      } finally {
        this.busy = false;
      }
    },
  }));
});
