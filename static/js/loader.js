// Indicador de carga: cada navegación pide la página al servidor, y en la PWA instalada
// no hay barra del navegador que muestre que algo está pasando. Al tocar un link o mandar
// un formulario se prende la barra de arriba (html.is-loading) y el botón que envió el
// formulario muestra un spinner; un segundo envío del mismo formulario se ignora para no
// cargar dos veces el mismo gasto.
(() => {
  const root = document.documentElement;

  function start() {
    root.classList.add("is-loading");
  }

  function reset() {
    root.classList.remove("is-loading");
    for (const el of document.querySelectorAll("[data-submitting]")) delete el.dataset.submitting;
    for (const el of document.querySelectorAll('[aria-busy="true"]')) el.removeAttribute("aria-busy");
  }

  function leavesPage(link, event) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if ((link.target && link.target !== "_self") || link.hasAttribute("download")) return false;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return false;
    // Solo cambia el ancla: el navegador no pide nada.
    return !(url.hash && url.pathname === location.pathname && url.search === location.search);
  }

  // En burbujeo, así los handlers propios (confirm(), @submit.prevent) deciden antes.
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (link && !event.defaultPrevented && leavesPage(link, event)) start();
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || (event.submitter || form).getAttribute("formtarget") || form.target) return;
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "1";
    if (event.submitter) event.submitter.setAttribute("aria-busy", "true");
    start();
  });

  // Volver atrás puede restaurar la página tal como quedó (bfcache), con la barra prendida.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) reset();
  });
})();
