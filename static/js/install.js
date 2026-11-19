// Botón "Instalar app" ($store.install, ver templates/pwa/_install_card.html).
// Se carga antes que Alpine para que el store exista en "alpine:init".
//   mode "prompt": Chrome/Android ofreció instalar (beforeinstallprompt) → instala directo.
//   mode "ios":    iPhone/iPad sin instalar → no hay API para instalar, se muestran los pasos.
//   mode "none":   ya corre instalada, o el navegador no permite instalarla desde la página.
// Desde Safari no se puede saber si la app ya está instalada en el inicio: ahí el botón
// sigue apareciendo, pero dentro de la app instalada nunca.
(() => {
  let deferredPrompt = null;

  const standalone = () =>
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  // No hay forma de detectar por capacidad "se puede agregar al inicio con Safari".
  // iPadOS se presenta como Mac: se distingue por la pantalla táctil.
  const ios =
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  const store = () => window.Alpine?.store("install");

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    if (store() && !standalone()) store().mode = "prompt";
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    if (store()) store().mode = "none";
  });

  document.addEventListener("alpine:init", () => {
    window.Alpine.store("install", {
      mode: standalone() ? "none" : deferredPrompt ? "prompt" : ios ? "ios" : "none",
      guideOpen: false,

      install() {
        if (this.mode === "ios") {
          this.guideOpen = !this.guideOpen;
          return;
        }
        if (!deferredPrompt) return;
        // El aviso de Chrome se puede mostrar una sola vez: el botón se va ya. Si lo
        // rechaza, Chrome lo vuelve a ofrecer en otra visita (nuevo beforeinstallprompt).
        deferredPrompt.prompt();
        deferredPrompt = null;
        this.mode = "none";
      },
    });
  });
})();
