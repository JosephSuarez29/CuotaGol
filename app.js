/*
  app.js
  ------
  Lee predictions.json y construye las tarjetas + filtros de liga automáticamente.
  Para agregar un pronóstico nuevo: solo edita predictions.json, no toques este archivo.
*/

const AD_SLOT_EVERY = 3; // inserta un espacio publicitario cada N tarjetas
const SHOW_AD_SLOTS = false; // cámbialo a true cuando tengas anuncios/afiliados reales que mostrar

function confidenceDots(level) {
  let dots = '';
  for (let i = 1; i <= 4; i++) {
    dots += `<i class="${i <= level ? 'on' : ''}"></i>`;
  }
  return dots;
}

function cardHTML(p) {
  return `
    <div class="card" data-league="${p.league}">
      <div class="card-league"><b>${p.league}</b><span>${p.date}</span></div>
      <div class="ticket-teams">
        <div class="team"><div class="badge" style="background:${p.team1.color}">${p.team1.abbr}</div><span>${p.team1.name}</span></div>
        <span class="vs">VS</span>
        <div class="team"><div class="badge" style="background:${p.team2.color}">${p.team2.abbr}</div><span>${p.team2.name}</span></div>
      </div>
      <div class="card-pick-label">Pronóstico</div>
      <div class="card-pick">${p.pick}</div>
      <div class="card-foot">
        <a href="detalle.html?id=${p.id}" class="card-link">Ver análisis →</a>
        <span class="ticket-conf" style="margin:0"><span class="conf-dots">${confidenceDots(p.confidence)}</span></span>
      </div>
    </div>
  `;
}

function adSlotHTML() {
  return `<div class="ad-slot">Espacio publicitario · 728×90 (aquí irá tu bloque de anuncios / afiliado)</div>`;
}

function renderFilters(predictions) {
  const filtersEl = document.querySelector('.filters');
  const leagues = [...new Set(predictions.map(p => p.league))];

  filtersEl.innerHTML = `<span class="filter active" data-league="all">Todos</span>` +
    leagues.map(l => `<span class="filter" data-league="${l}">${l}</span>`).join('');

  filtersEl.querySelectorAll('.filter').forEach(f => {
    f.addEventListener('click', () => {
      filtersEl.querySelectorAll('.filter').forEach(x => x.classList.remove('active'));
      f.classList.add('active');
      const chosen = f.dataset.league;
      document.querySelectorAll('#cardGrid .card').forEach(card => {
        card.style.display = (chosen === 'all' || card.dataset.league === chosen) ? '' : 'none';
      });
    });
  });
}

function renderCards(predictions) {
  const grid = document.getElementById('cardGrid');
  let html = '';
  predictions.forEach((p, i) => {
    html += cardHTML(p);
    if (SHOW_AD_SLOTS && (i + 1) % AD_SLOT_EVERY === 0 && i !== predictions.length - 1) {
      html += adSlotHTML();
    }
  });
  grid.innerHTML = html;

  // Reveal animation (igual que antes)
  const cards = grid.querySelectorAll('.card');
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          setTimeout(() => entry.target.classList.add('visible'), i * 60);
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.15 });
    cards.forEach(c => io.observe(c));
  } else {
    cards.forEach(c => c.classList.add('visible'));
  }
}

/* ---------- Historial ---------- */

function histRowHTML(h) {
  const resultLabel = h.result === 'acierto' ? '✓ Acierto' : '✗ Falló';
  return `
    <div class="hist-row">
      <span class="hist-date">${h.date}</span>
      <div>
        <div class="hist-league">${h.league}</div>
        <div class="hist-match">${h.team1} vs ${h.team2}</div>
      </div>
      <span class="hist-pick">${h.pick}</span>
      <span class="hist-result ${h.result}">${resultLabel}</span>
    </div>
  `;
}

function renderHistorial(historial) {
  const list = document.getElementById('histList');
  if (!list) return;
  // más reciente primero; se asume que el archivo ya viene ordenado, pero por si acaso no se reordena para no asumir formato de fecha
  list.innerHTML = historial.map(histRowHTML).join('');

  const total = historial.length;
  const aciertos = historial.filter(h => h.result === 'acierto').length;
  const pct = total > 0 ? Math.round((aciertos / total) * 100) : 0;

  const badge = document.getElementById('historialBadgeText');
  if (badge) badge.textContent = `${pct}%`;

  const statAccuracy = document.getElementById('statAccuracy');
  const statTotal = document.getElementById('statTotal');
  if (statAccuracy) statAccuracy.textContent = `${pct}%`;
  if (statTotal) statTotal.textContent = total;
}

/* ---------- Carga de datos ---------- */

fetch('predictions.json')
  .then(res => res.json())
  .then(predictions => {
    renderCards(predictions);
    renderFilters(predictions);

    const statLeagues = document.getElementById('statLeagues');
    if (statLeagues) {
      const leagues = new Set(predictions.map(p => p.league));
      statLeagues.textContent = leagues.size;
    }
  })
  .catch(err => {
    console.error('No se pudo cargar predictions.json', err);
    document.getElementById('cardGrid').innerHTML =
      '<p style="color:var(--text-muted)">No se pudieron cargar los pronósticos.</p>';
  });

fetch('historial.json')
  .then(res => res.json())
  .then(historial => renderHistorial(historial))
  .catch(err => {
    console.error('No se pudo cargar historial.json', err);
    const list = document.getElementById('histList');
    if (list) list.innerHTML = '<p style="color:var(--text-muted)">Aún no hay historial disponible.</p>';
  });
