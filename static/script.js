/* ============================================
   RELÓGIO
============================================ */
function initClock() {
  const clockEl = document.getElementById("clock");
  if (!clockEl) return;

  function tick() {
    const now = new Date();
    clockEl.textContent = now.toLocaleString("pt-PT");
  }

  tick();
  setInterval(tick, 1000);
}

/* ============================================
   PÁGINA DE PESQUISA
============================================ */
function initSearchPage() {
  const input = document.getElementById("searchInput");
  const status = document.getElementById("searchStatus");
  const resultsContainer = document.getElementById("resultsContainer");
  const resultsList = document.getElementById("resultsList");

  if (!input) return;

  async function fazerPesquisa() {
    const q = input.value.trim();
    if (!q) {
      status.textContent = "Escreve o nome da rádio e carrega em Enter.";
      resultsContainer.style.display = "none";
      resultsList.innerHTML = "";
      return;
    }

    status.textContent = "A procurar rádios...";
    resultsContainer.style.display = "block";
    resultsList.innerHTML = "";

    try {
      const resp = await fetch(`/api/search_all?q=${encodeURIComponent(q)}`);
      const data = await resp.json();

      if (!data.ok || !data.radios.length) {
        status.textContent = "Nenhuma rádio encontrada.";
        resultsList.innerHTML = "<p>Sem resultados.</p>";
        return;
      }

      status.textContent = `Encontradas ${data.radios.length} rádios.`;
      resultsList.innerHTML = "";

      data.radios.forEach(st => {
        const div = document.createElement("div");
        div.className = "result-item";
        div.innerHTML = `
          <div>
            <strong>${st.name}</strong>
            <span class="country">${st.country || ""}</span>
            <div class="clicks">🔥 ${st.clickcount || 0} cliques</div>
          </div>
          <a href="/radio/${st.id}" class="btn small">▶ Ouvir</a>
        `;
        resultsList.appendChild(div);
      });

    } catch (err) {
      console.error(err);
      status.textContent = "Erro ao pesquisar.";
      resultsList.innerHTML = "<p>Erro ao pesquisar.</p>";
    }
  }

  input.addEventListener("keyup", e => {
    if (e.key === "Enter") fazerPesquisa();
  });

  /* ───────── SUGESTÃO: TOP100 ───────── */
  window.loadTop100 = async function () {
    const box = document.getElementById("top100List");
    if (!box) return;

    box.innerHTML = "<p>A carregar Top 100...</p>";

    try {
      const r = await fetch("/api/suggest/top100");
      const data = await r.json();
      box.innerHTML = "";

      if (!data.ok || !data.radios) {
        box.innerHTML = "<p>Erro ao carregar Top 100.</p>";
        return;
      }

      data.radios.forEach(st => {
        const div = document.createElement("div");
        div.className = "result-item";
        div.innerHTML = `
          <div>
            <strong>${st.name}</strong>
            <span class="country">${st.country || ""}</span>
            <div class="clicks">🔥 ${st.clickcount || 0} cliques</div>
          </div>
          <a href="/radio/${st.id}" class="btn small">▶ Ouvir</a>
        `;
        box.appendChild(div);
      });

    } catch (err) {
      console.error("Erro Top100:", err);
      box.innerHTML = "<p>Erro ao carregar Top 100.</p>";
    }
  };

  /* ───────── SUGESTÃO: GÉNERO ───────── */
  window.loadGenre = async function (g) {
    const box = document.getElementById("genreList");
    if (!box) return;

    box.innerHTML = `<p>A carregar ${g}...</p>`;

    try {
      const r = await fetch(`/api/suggest/genre?g=${encodeURIComponent(g)}`);
      const data = await r.json();
      box.innerHTML = "";

      if (!data.ok || !data.radios) {
        box.innerHTML = "<p>Sem resultados.</p>";
        return;
      }

      data.radios.forEach(st => {
        const div = document.createElement("div");
        div.className = "result-item";
        div.innerHTML = `
          <div>
            <strong>${st.name}</strong>
            <span class="country">${st.country || ""}</span>
          </div>
          <a href="/radio/${st.id}" class="btn small">▶ Ouvir</a>
        `;
        box.appendChild(div);
      });

    } catch (err) {
      console.error("Erro genre:", err);
      box.innerHTML = "<p>Erro ao carregar género.</p>";
    }
  };

  /* ───────── SUGESTÃO: PAÍS ───────── */
  window.loadCountry = async function (c) {
    const box = document.getElementById("countryList");
    if (!box) return;

    box.innerHTML = `<p>A carregar ${c}...</p>`;

    try {
      const r = await fetch(`/api/suggest/country?c=${encodeURIComponent(c)}`);
      const data = await r.json();
      box.innerHTML = "";

      if (!data.ok || !data.radios) {
        box.innerHTML = "<p>Sem resultados.</p>";
        return;
      }

      data.radios.forEach(st => {
        const div = document.createElement("div");
        div.className = "result-item";
        div.innerHTML = `
          <div>
            <strong>${st.name}</strong>
            <span class="country">${st.country || ""}</span>
            <div class="clicks">🔥 ${st.clickcount || 0} cliques</div>
          </div>
          <a href="/radio/${st.id}" class="btn small">▶ Ouvir</a>
        `;
        box.appendChild(div);
      });

    } catch (err) {
      console.error("Erro country:", err);
      box.innerHTML = "<p>Erro ao carregar país.</p>";
    }
  };

  /* Carregar Top100 automaticamente */
  loadTop100();
}

/* ============================================
   PÁGINA DO PLAYER
============================================ */
function initPlayerPage() {
  const audio = document.getElementById("audio");
  const coverImg = document.getElementById("coverImg");
  const coverFrame = document.getElementById("coverFrame");
  const artistNow = document.getElementById("artistNow");
  const songNow = document.getElementById("songNow");
  const timeNow = document.getElementById("timeNow");
  const statusText = document.getElementById("statusText");
  const historyList = document.getElementById("historyList");
  const btnPlayPause = document.getElementById("btnPlayPause");
  const btnReload = document.getElementById("btnReload");
  const eqCanvas = document.getElementById("eqCanvas");
  const ctx = eqCanvas.getContext("2d");

  let isPlaying = false;
  let ultimoArtist = "";
  let ultimoSong = "";

  /* ───────── PLAY/PAUSE ───────── */
  btnPlayPause.addEventListener("click", () => {
    if (!isPlaying) {
      statusText.textContent = "A iniciar stream...";
      audio.src = `/proxy/${RADIO_ID}`;
      audio.load();
      audio.play()
        .then(() => {
          isPlaying = true;
          btnPlayPause.textContent = "⏸ Pausar";
          statusText.textContent = "A reproduzir...";
          coverFrame.classList.add("spin");
          iniciarEQ(audio, eqCanvas, ctx, coverFrame);
        })
        .catch(() => {
          statusText.textContent = "Clique novamente para iniciar.";
        });
    } else {
      audio.pause();
      isPlaying = false;
      btnPlayPause.textContent = "▶ Reproduzir";
      coverFrame.classList.remove("spin");
    }
  });

  audio.addEventListener("pause", () => {
    isPlaying = false;
    btnPlayPause.textContent = "▶ Reproduzir";
    coverFrame.classList.remove("spin");
  });

  /* ───────── RECONECTAR ───────── */
  function tentarReconectar() {
    if (!isPlaying) return;
    audio.src = `/proxy/${RADIO_ID}`;
    audio.load();
    audio.play().catch(() => {});
  }

  audio.addEventListener("error", tentarReconectar);
  audio.addEventListener("stalled", tentarReconectar);
  audio.addEventListener("ended", tentarReconectar);

  /* ───────── NOW PLAYING ───────── */
  async function atualizarMusica() {
    try {
      const resp = await fetch(`/api/nowplaying?station=${encodeURIComponent(RADIO_ID)}`);
      const data = await resp.json();

      if (!data.ok) return;

      const novoArtist = data.artist || "Desconhecido";
      const novoSong = data.song || "Desconhecido";

      if (novoArtist !== ultimoArtist || novoSong !== ultimoSong) {
        const meta = document.querySelector(".track-meta");
        meta.classList.remove("flash");
        void meta.offsetWidth;
        meta.classList.add("flash");
        ultimoArtist = novoArtist;
        ultimoSong = novoSong;
      }

      artistNow.textContent = novoArtist;
      songNow.textContent = novoSong;
      timeNow.textContent = data.time || "";

      carregarCapa(novoArtist, novoSong);
      carregarHistorico();

    } catch (err) {
      console.error("Erro nowplaying:", err);
    }
  }

  btnReload.addEventListener("click", atualizarMusica);

  /* ───────── CAPA ───────── */
  async function carregarCapa(artist, song) {
    const a = artist.trim();
    const s = song.trim();

    if (!a || !s || (a === "Desconhecido" && s === "Desconhecido")) {
      coverImg.src = "/static/default_cover.png";
      return;
    }

    const key = `cover_${a}__${s}`;
    const cache = localStorage.getItem(key);

    if (cache) {
      coverImg.src = cache;
      return;
    }

    try {
      const resp = await fetch(`/api/cover?artist=${encodeURIComponent(a)}&song=${encodeURIComponent(s)}`);
      const data = await resp.json();
      const url = data.cover || "/static/default_cover.png";

      coverImg.src = url;
      localStorage.setItem(key, url);

    } catch {
      coverImg.src = "/static/default_cover.png";
    }
  }

  /* ───────── HISTÓRICO ───────── */
  async function carregarHistorico() {
    try {
      const resp = await fetch(`/api/history?station=${encodeURIComponent(RADIO_ID)}`);
      const data = await resp.json();

      historyList.innerHTML = "";

      if (!data.tracks.length) {
        historyList.innerHTML = "<li>Sem histórico ainda.</li>";
        return;
      }

      data.tracks.forEach(t => {
        const li = document.createElement("li");
        li.textContent = `${t.time} — ${t.artist} - ${t.song}`;
        historyList.appendChild(li);
      });

    } catch (err) {
      console.error("Erro histórico:", err);
    }
  }

  /* Atualizar */
  setInterval(atualizarMusica, 12000);
  atualizarMusica();
}

/* ============================================
   EQ CIRCULAR — NEON ESPACIAL
============================================ */
let audioCtx = null;
let analyser = null;
let dataArray = null;
let bufferLength = 0;
let eqAnimId = null;
const particles = [];

function iniciarEQ(audio, eqCanvas, ctx, coverFrame) {
  if (audioCtx) {
    if (audioCtx.state === "suspended") audioCtx.resume();
    return;
  }

  const ACtx = window.AudioContext || window.webkitAudioContext;
  if (!ACtx) {
    console.warn("Web Audio API não disponível.");
    return;
  }

  audioCtx = new ACtx();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512;
  bufferLength = analyser.frequencyBinCount;
  dataArray = new Uint8Array(bufferLength);

  const source = audioCtx.createMediaElementSource(audio);
  source.connect(analyser);
  analyser.connect(audioCtx.destination);

  desenharEQCircular(eqCanvas, ctx, coverFrame);
}

function desenharEQCircular(eqCanvas, ctx, coverFrame) {
  eqAnimId = requestAnimationFrame(() => desenharEQCircular(eqCanvas, ctx, coverFrame));
  if (!analyser) return;

  analyser.getByteFrequencyData(dataArray);

  const w = eqCanvas.width;
  const h = eqCanvas.height;
  const cx = w / 2;
  const cy = h / 2;

  ctx.clearRect(0, 0, w, h);

  const innerRadius = 90;
  const maxBarLen = 40;
  const bars = bufferLength;

  const now = performance.now() / 1000;

  let bass = 0;
  for (let i = 0; i < 40; i++) bass += dataArray[i];
  const bassLevel = bass / 40 / 255;

  coverFrame.style.boxShadow = `0 0 ${30 + bassLevel * 50}px rgba(0, 200, 255, ${0.6 + bassLevel})`;

  const baseHue = 190 + Math.sin(now * 0.3) * 40;

  for (let i = 0; i < bars; i++) {
    const v = dataArray[i] / 255;
    const len = 8 + v * maxBarLen;
    const angle = i / bars * Math.PI * 2;

    const r0 = innerRadius;
    const r1 = innerRadius + len;

    const x0 = cx + r0 * Math.cos(angle);
    const y0 = cy + r0 * Math.sin(angle);
    const x1 = cx + r1 * Math.cos(angle);
    const y1 = cy + r1 * Math.sin(angle);

    const hue = baseHue + Math.sin(angle * 2 + now) * 30;

    const grad = ctx.createLinearGradient(x0, y0, x1, y1);
    grad.addColorStop(0, `hsla(${hue}, 70%, 30%, 0)`);
    grad.addColorStop(1, `hsla(${hue}, 90%, 70%, 1)`);

    ctx.strokeStyle = grad;
    ctx.lineWidth = 2.2;
    ctx.shadowBlur = 15;
    ctx.shadowColor = `hsla(${hue}, 100%, 70%, 0.9)`;

    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();

    if (v > 0.65 && Math.random() < v * 0.3) {
      particles.push({
        angle: angle,
        radius: r1,
        alpha: 1,
        speed: 15 + v * 40
      });
    }
  }

  ctx.shadowBlur = 0;

  for (let p = particles.length - 1; p >= 0; p--) {
    const particle = particles[p];
    particle.radius += particle.speed * 0.016;
    particle.alpha -= 0.02;

    if (particle.alpha <= 0) {
      particles.splice(p, 1);
      continue;
    }

    const px = cx + particle.radius * Math.cos(particle.angle);
    const py = cy + particle.radius * Math.sin(particle.angle);

    ctx.fillStyle = `rgba(100,200,255,${particle.alpha})`;
    ctx.beginPath();
    ctx.arc(px, py, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
}

/* ============================================
   INIT GLOBAL
============================================ */
document.addEventListener("DOMContentLoaded", () => {
  initClock();
  if (document.getElementById("searchInput")) initSearchPage();
  if (document.getElementById("audio")) initPlayerPage();
});
