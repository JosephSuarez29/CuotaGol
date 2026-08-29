/*
  app.js
  ------
  Lee predictions.json y construye las tarjetas + filtros de liga automáticamente.
  Para agregar un pronóstico nuevo: solo edita predictions.json, no toques este archivo.
*/

const AD_SLOT_EVERY = 3; // inserta un espacio publicitario cada N tarjetas

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
        <a href="#" class="card-link">Ver análisis →</a>
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
    if ((i + 1) % AD_SLOT_EVERY === 0 && i !== predictions.length - 1) {
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

fetch('predictions.json')
  .then(res => res.json())
  .then(predictions => {
    renderCards(predictions);
    renderFilters(predictions);
  })
  .catch(err => {
    console.error('No se pudo cargar predictions.json', err);
    document.getElementById('cardGrid').innerHTML =
      '<p style="color:var(--text-muted)">No se pudieron cargar los pronósticos.</p>';
  });
