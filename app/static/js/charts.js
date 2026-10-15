// Tema común de las gráficas: toma los colores de las variables CSS (claro/oscuro)
// para que Chart.js vaya a juego con el resto de la página. Cargar después de chart.min.js.
(function () {
  var css = getComputedStyle(document.documentElement);
  var v = function (nombre) { return css.getPropertyValue(nombre).trim(); };

  window.tema = {
    ingresos: v('--accent-ink'),
    gastos: v('--crit'),
    neutro: v('--muted'),
    superficie: v('--surface'),
    eur: function (x) {
      return x.toLocaleString('es-ES', { maximumFractionDigits: 0 }) + ' €';
    },
    // Mismo color con transparencia (para los meses que aún son previsión).
    suave: function (color) { return 'color-mix(in srgb, ' + color + ' 40%, transparent)'; },
  };

  Chart.defaults.color = v('--muted');
  Chart.defaults.borderColor = v('--border');
  Chart.defaults.font.family = v('--font');
  Chart.defaults.font.size = 12;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.elements.bar.borderRadius = 4;
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.plugins.legend.position = 'bottom';
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.tooltip.callbacks.label = function (ctx) {
    var valor = ctx.parsed.y !== undefined && ctx.chart.options.indexAxis !== 'y' ? ctx.parsed.y : ctx.parsed.x;
    return (ctx.dataset.label ? ctx.dataset.label + ': ' : '') + window.tema.eur(valor);
  };
  Chart.defaults.scale.grid.drawTicks = false;
  Chart.defaults.scale.ticks.padding = 8;
})();
