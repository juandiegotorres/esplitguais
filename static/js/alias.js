// Se carga antes que Alpine para que los componentes estén registrados en "alpine:init".
document.addEventListener("alpine:init", () => {
  // Copia el texto de data-copy del elemento raíz. navigator.clipboard solo existe en
  // contextos seguros (HTTPS o localhost); si falla, se usa el método viejo con un textarea.
  window.Alpine.data("copyText", () => ({
    copied: false,
    timer: null,
    async copy() {
      const text = this.$root.dataset.copy || "";
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      this.copied = true;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => (this.copied = false), 2000);
    },
  }));

  // Formulario de pago: si quien paga sos vos (data-me), muestra el alias de quien recibe
  // según el <select name="to_user">. Los alias vienen de un json_script cuyo id va en
  // data-aliases.
  window.Alpine.data("recipientAlias", () => ({
    aliases: {},
    me: "",
    from: "",
    to: "",
    init() {
      const source = document.getElementById(this.$root.dataset.aliases);
      this.aliases = source ? JSON.parse(source.textContent) : {};
      this.me = this.$root.dataset.me || "";
      for (const name of ["from", "to"]) {
        const select = this.$root.querySelector(`[name="${name}_user"]`);
        if (select) {
          this[name] = select.value;
          select.addEventListener("change", () => (this[name] = select.value));
        }
      }
    },
    get paying() {
      return this.from !== "" && this.from === this.me && this.to !== "";
    },
    get alias() {
      return this.paying ? this.aliases[this.to] || "" : "";
    },
  }));
});
