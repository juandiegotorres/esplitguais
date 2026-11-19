// Indicador de carga: cada navegación pide la página al servidor, y en la PWA instalada
// no hay barra del navegador que muestre que algo está pasando. Al tocar un link o mandar
// un formulario se prende html.is-loading (barra arriba y contenido atenuado, ver app.css)
// y el botón que envió el formulario muestra un spinner; un segundo envío del mismo
// formulario se ignora para no cargar dos veces el mismo gasto. En las pestañas, la tocada
// pasa a verse activa al instante, donde está mirando quien la tocó.
(() => {
  const root = document.documentElement;
  // [pestaña tocada, pestaña que estaba activa], para deshacerlo al volver atrás.
  let movedTab = null;

  function start(kind) {
    root.classList.add("is-loading", kind);
  }

  function markTab(link) {
    const nav = link.closest(".tabbar, .subtabs");
    const current = nav?.querySelector('[aria-current="page"]');
    if (!nav || link === current || link.classList.contains("tabbar-add")) return;
    current?.removeAttribute("aria-current");
    link.setAttribute("aria-current", "page");
    movedTab = [link, current];
  }

  function reset() {
    root.classList.remove("is-loading", "is-navigating", "is-submitting");
    for (const el of document.querySelectorAll("[data-submitting]")) delete el.dataset.submitting;
    for (const el of document.querySelectorAll('[aria-busy="true"]')) el.removeAttribute("aria-busy");
    if (movedTab) {
      const [link, previous] = movedTab;
      link.removeAttribute("aria-current");
      previous?.setAttribute("aria-current", "page");
      movedTab = null;
    }
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
    if (!link || event.defaultPrevented || !leavesPage(link, event)) return;
    markTab(link);
    start("is-navigating");
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
    start("is-submitting");
  });

  // Volver atrás puede restaurar la página tal como quedó (bfcache), con la barra prendida.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) reset();
  });
})();
