/* HayaFlash — graphiques Chart.js declaratifs (statistiques vendeur, admin plateforme).
 *
 * <canvas data-hf-chart="line|bar"            type de graphique
 *         data-hf-chart-data="id"             <script type="application/json" id="id">
 *                                             produit par {{ liste|json_script:"id" }}
 *         data-hf-chart-x="day"               cle des libelles (axe X)
 *         data-hf-chart-y="revenue"           cle des valeurs (defaut : revenue)
 *         data-hf-chart-label="CA (FCFA)"     legende du jeu de donnees
 *         data-hf-chart-color="#E63946">      couleur
 *
 * Ex-scripts inline de flash_sales/analytics_dashboard.html et
 * core/platform_admin.html (CSP, GOVERNANCE_SECURITE.md categorie 4).
 */
document.addEventListener('DOMContentLoaded', function () {
  if (!window.Chart) return;
  document.querySelectorAll('canvas[data-hf-chart]').forEach(function (canvas) {
    var src = document.getElementById(canvas.dataset.hfChartData);
    var rows = src ? JSON.parse(src.textContent) : [];
    if (!rows.length) return;
    var type = canvas.dataset.hfChart;
    var xKey = canvas.dataset.hfChartX;
    var yKey = canvas.dataset.hfChartY || 'revenue';
    var color = canvas.dataset.hfChartColor || '#E63946';
    var dataset = {
      label: canvas.dataset.hfChartLabel || '',
      data: rows.map(function (d) { return d[yKey]; }),
    };
    if (type === 'line') {
      dataset.borderColor = color;
      dataset.backgroundColor = 'rgba(230,57,70,0.08)';
      dataset.fill = true;
      dataset.tension = 0.3;
      dataset.pointRadius = 3;
    } else {
      dataset.backgroundColor = color;
      dataset.borderRadius = 6;
    }
    new window.Chart(canvas, {
      type: type,
      data: { labels: rows.map(function (d) { return d[xKey]; }), datasets: [dataset] },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });
  });
});
