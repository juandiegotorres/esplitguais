// Formulario de gasto: sumas en vivo y vista previa del reparto.
// Solo ayuda visual: el servidor valida y calcula los importes definitivos.
// Los importes se manejan en centavos enteros (BigInt en las divisiones).
document.addEventListener("alpine:init", () => {
  // "15000" | "15.000" | "15.000,50" | "$ 1.234,56" → centavos; null si no se entiende.
  function parseAmount(text) {
    let s = String(text || "").replace(/[$\s]/g, "");
    if (!s) return null;
    if (s.includes(",")) {
      s = s.replace(/\./g, "").replace(",", ".");
    } else if (/^\d{1,3}(\.\d{3})+$/.test(s)) {
      s = s.replace(/\./g, "");
    }
    const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(s);
    if (!m) return null;
    return Number(m[1]) * 100 + Number((m[2] || "").padEnd(2, "0"));
  }

  // Porcentaje o partes con hasta 4 decimales → entero escalado ×10000; null si inválido.
  function parseScaled(text) {
    const s = String(text || "").replace(/\s/g, "").replace(",", ".");
    if (!s) return null;
    const m = /^(\d+)(?:\.(\d{1,4}))?$/.exec(s);
    if (!m) return null;
    return Number(m[1]) * 10000 + Number((m[2] || "").padEnd(4, "0"));
  }

  function formatArs(cents) {
    const negative = cents < 0;
    const abs = Math.abs(cents);
    const units = Math.floor(abs / 100)
      .toString()
      .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    const decimals = String(abs % 100).padStart(2, "0");
    return (negative ? "-$ " : "$ ") + units + "," + decimals;
  }

  function formatScaled(scaled) {
    const units = Math.floor(scaled / 10000);
    const frac = String(scaled % 10000).padStart(4, "0").replace(/0+$/, "");
    return frac ? units + "," + frac : String(units);
  }

  // Reparto proporcional a pesos enteros; el resto va a los primeros por id.
  function allocate(totalCents, weights, denominator) {
    const ids = Object.keys(weights).sort((a, b) => Number(a) - Number(b));
    const result = {};
    if (!denominator) return result;
    const total = BigInt(totalCents);
    const denom = BigInt(denominator);
    let assigned = 0;
    for (const id of ids) {
      result[id] = Number((total * BigInt(weights[id])) / denom);
      assigned += result[id];
    }
    let remainder = totalCents - assigned;
    const weightSum = ids.reduce((acc, id) => acc + weights[id], 0);
    if (weightSum === denominator) {
      for (const id of ids) {
        if (remainder <= 0) break;
        result[id] += 1;
        remainder -= 1;
      }
    }
    return result;
  }

  Alpine.data("expenseForm", () => {
    const state = JSON.parse(document.getElementById("expense-form-state").textContent);
    return {
      ...state,

      formatArs,

      get amountCents() {
        return parseAmount(this.amount);
      },

      get payersTotal() {
        return this.members.reduce((acc, m) => acc + (parseAmount(this.payerAmounts[m.id]) || 0), 0);
      },

      get exactTotal() {
        return this.members.reduce((acc, m) => acc + (parseAmount(this.exact[m.id]) || 0), 0);
      },

      get percentTotal() {
        return this.members.reduce((acc, m) => acc + (parseScaled(this.percent[m.id]) || 0), 0);
      },

      get percentLabel() {
        return "Σ " + formatScaled(this.percentTotal) + " %";
      },

      get percentOk() {
        return this.percentTotal === 100 * 10000;
      },

      // Texto "Faltan $ X" / "Sobran $ X" / "Cuadra" respecto del importe total.
      differenceLabel(total) {
        if (this.amountCents === null) return "Cargá el importe";
        const diff = this.amountCents - total;
        if (diff > 0) return "Faltan " + formatArs(diff);
        if (diff < 0) return "Sobran " + formatArs(-diff);
        return "Cuadra";
      },

      differenceOk(total) {
        return this.amountCents !== null && this.amountCents === total;
      },

      // Reparte 100 % entre todos los miembros; el último absorbe el resto (≤ 4 decimales).
      splitPercentEvenly() {
        const n = this.members.length;
        if (!n) return;
        const each = Math.floor((100 * 10000) / n);
        this.members.forEach((m, i) => {
          const scaled = i === n - 1 ? 100 * 10000 - each * (n - 1) : each;
          this.percent[m.id] = formatScaled(scaled);
        });
      },

      // Asigna lo que falta para 100 % al último miembro vacío (o al último de la lista).
      completePercent() {
        const empty = this.members.filter((m) => !parseScaled(this.percent[m.id]));
        const target = empty.length ? empty[empty.length - 1] : this.members[this.members.length - 1];
        if (!target) return;
        const others = this.percentTotal - (parseScaled(this.percent[target.id]) || 0);
        const rest = 100 * 10000 - others;
        this.percent[target.id] = rest > 0 ? formatScaled(rest) : "";
      },

      // user_id → centavos que le tocan, según el tipo de reparto elegido.
      get preview() {
        const amount = this.amountCents;
        if (amount === null || amount <= 0) return {};
        if (this.splitType === "equal") {
          const weights = {};
          for (const id of this.participants) weights[id] = 1;
          return allocate(amount, weights, this.participants.length);
        }
        if (this.splitType === "exact") {
          const result = {};
          for (const m of this.members) {
            const cents = parseAmount(this.exact[m.id]);
            if (cents) result[m.id] = cents;
          }
          return result;
        }
        if (this.splitType === "percent") {
          const weights = {};
          for (const m of this.members) {
            const w = parseScaled(this.percent[m.id]);
            if (w) weights[m.id] = w;
          }
          return allocate(amount, weights, 100 * 10000);
        }
        const weights = {};
        for (const m of this.members) {
          const w = parseScaled(this.units[m.id]);
          if (w) weights[m.id] = w;
        }
        const sum = Object.values(weights).reduce((acc, w) => acc + w, 0);
        return allocate(amount, weights, sum);
      },

      previewFor(id) {
        const cents = this.preview[id];
        return cents ? formatArs(cents) : "—";
      },
    };
  });
});
