/* ============================================
   Utilitários gerais (relógio)
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

      if (!data.ok || !data.radios || !data.radios.length) {
        status.textContent = "Nenhuma rádio encontrada.";
        resultsList.innerHTML = "<p style='text-align:left;'>Sem resultados.</p>";
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
          </div>
          <a href="/radio/${st.id}" class="btn small">▶ Ouvir</a>
        `;
        resultsList.appendChild(div);
      });
    } catch (err) {
      console.error("Erro na pesquisa:", err);
      status.textContent = "Erro ao pesquisar rádios.";
      resultsList.innerHTML = "<p>Erro ao pesquisar.</p>";
    }
  }

  input.addEventListener("keyup", (e) => {
    if (e.key === "Enter") {
      fazerPesquisa();
    }
  });

  // Sugestões (Top100 / género / país)
  window.loadTop100 = async function() {
    const box = document.getElementById("top100List");
    if (!box) return;
    box.innerHTML = "<p>A carregar Top 100...</p>";
    try {
      const r = await fetch("/api/suggest/top100");
      const data = await r.json();
      box.innerHTML = "";
      if (!data.ok || !data.radios) {
        box.innerHTML = "<p>Não foi possível carregar Top 100.</p>";
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
      console.error("Erro Top100:", err);
      box.innerHTML = "<p>Erro ao carregar Top 100.</p>";
    }
  };

  window.loadGenre = async function(g) {
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

  window.loadCountry = async function(c) {
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

  // carrega Top100 logo à entrada
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
  let lastTime = 0;

  /* ========= RECONNECTOR GLOBAL ========= */
  function reconnect(reason = "") {
    console.log("🔁 Reconectar stream…", reason);
    statusText.textContent = "A reconectar…";

    const pos = audio.currentTime;

    audio.src = `/proxy/${RADIO_ID}?t=${Date.now()}`;
    audio.load();

    audio.play().then(() => {
      statusText.textContent = "A reproduzir…";
      isPlaying = true;
      coverFrame.classList.add("spin");
      iniciarEQ(audio, eqCanvas, ctx, coverFrame);
      audio.currentTime = pos;
    }).catch(err => {
      console.log("⚠️ Falhou reconexão:", err);
    });
  }

  /* ========= BOTÃO PLAY ========= */
  btnPlayPause.addEventListener("click", () => {
    if (!isPlaying) {
      audio.src = `/proxy/${RADIO_ID}`;
      audio.load();
      audio.play().then(() => {
        isPlaying = true;
        btnPlayPause.textContent = "⏸ Pausar";
        statusText.textContent = "A reproduzir…";
        coverFrame.classList.add("spin");
        iniciarEQ(audio, eqCanvas, ctx, coverFrame);
      }).catch(err => {
        statusText.textContent = "Clique novamente para iniciar.";
      });
    } else {
      audio.pause();
      isPlaying = false;
      btnPlayPause.textContent = "▶ Reproduzir";
      coverFrame.classList.remove("spin");
    }
  });

  /* ========= EVENTOS QUE PARAM A RADIO ========= */
  ["error", "stalled", "abort", "waiting", "ended"].forEach(ev => {
    audio.addEventListener(ev, () => reconnect("Evento: " + ev));
  });

  /* ========= HEARTBEAT (deteta freeze) ========= */
  setInterval(() => {
    if (!isPlaying) return;

    if (audio.currentTime === lastTime) {
      reconnect("Heartbeat freeze");
    }

    lastTime = audio.currentTime;
  }, 20000); // 20s

  /* ========= FAILSAFE AUTO-RELOAD A CADA 4 MIN ========= */
  setInterval(() => {
    if (isPlaying) {
      reconnect("Failsafe 4 minutos");
    }
  }, 240000);

  /* ========= NOW PLAYING ========= */
  async function atualizarMusica() {
    try {
      const resp = await fetch(`/api/nowplaying?station=${encodeURIComponent(RADIO_ID)}`);
      const data = await resp.json();

      if (!data.ok) return;

      artistNow.textContent = data.artist || "Desconhecido";
      songNow.textContent = data.song || "Desconhecido";
      timeNow.textContent = data.time || "";

      carregarCapa(data.artist, data.song);
      carregarHistorico();
    } catch (err) {
      console.error("Erro atualização nowplaying:", err);
    }
  }

  setInterval(atualizarMusica, 12000);
  atualizarMusica();
}


  btnReload.addEventListener("click", atualizarMusica);

  /* CAPAS + CACHE */
  async function carregarCapa(artist, song) {
    const a = (artist || "").trim();
    const s = (song || "").trim();

    if (!a || !s || (a.toLowerCase() === "desconhecido" && s.toLowerCase() === "desconhecido")) {
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
      if (data.cover) localStorage.setItem(key, url);
    } catch (err) {
      console.error("Erro a carregar capa:", err);
      coverImg.src = "/static/default_cover.png";
    }
  }

  /* HISTÓRICO */
  async function carregarHistorico() {
    try {
      const resp = await fetch(`/api/history?station=${encodeURIComponent(RADIO_ID)}`);
      const data = await resp.json();
      historyList.innerHTML = "";

      if (!data.tracks || !data.tracks.length) {
        const li = document.createElement("li");
        li.textContent = "Sem histórico ainda.";
        historyList.appendChild(li);
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

  /* AUTO ATUALIZAR MÚSICA */
  setInterval(atualizarMusica, 12000);
  atualizarMusica();
}

/* ============================================
   EQ CIRCULAR — SPACE NEON
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
  if (!analyser || !dataArray) return;

  analyser.getByteFrequencyData(dataArray);

  const w = eqCanvas.width;
  const h = eqCanvas.height;
  const cx = w / 2;
  const cy = h / 2;

  ctx.clearRect(0, 0, w, h);

  const innerRadius = 90;
  const maxBarLen = 42;
  const bars = bufferLength;
  const now = performance.now() / 1000;

  // energia de graves
  let bassSum = 0;
  const bassBins = Math.min(40, bufferLength);
  for (let i = 0; i < bassBins; i++) {
    bassSum += dataArray[i] || 0;
  }
  const bassLevel = (bassSum / bassBins) / 255;
  const glowIntensity = 0.4 + bassLevel * 1.2;
  coverFrame.style.boxShadow =
    `0 0 ${25 + bassLevel * 40}px rgba(56,189,248,${glowIntensity})`;

  const baseHue = 200 + Math.sin(now * 0.3) * 40;

  for (let i = 0; i < bars; i++) {
    const raw = dataArray[i] || 0;
    const value = raw / 255;
    const barLen = 8 + value * maxBarLen;
    const angle = (i / bars) * Math.PI * 2;

    const r0 = innerRadius;
    const r1 = innerRadius + barLen;

    const x0 = cx + r0 * Math.cos(angle);
    const y0 = cy + r0 * Math.sin(angle);
    const x1 = cx + r1 * Math.cos(angle);
    const y1 = cy + r1 * Math.sin(angle);

    const hueShift = Math.sin(angle * 2 + now * 0.6) * 30;
    const hue = (baseHue + hueShift + 360) % 360;
    const sat = 85;
    const lightStart = 35;
    const lightEnd = 70;

    const grad = ctx.createLinearGradient(x0, y0, x1, y1);
    grad.addColorStop(0, `hsla(${hue}, ${sat}%, ${lightStart}%, 0.15)`);
    grad.addColorStop(1, `hsla(${hue}, ${sat}%, ${lightEnd}%, 1)`);

    ctx.lineWidth = 2.3;
    ctx.strokeStyle = grad;
    ctx.shadowBlur = 15;
    ctx.shadowColor = `hsla(${hue}, ${sat}%, ${lightEnd}%, 0.8)`;

    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();

    const offset = 4;
    const x0b = cx + (r0 + offset) * Math.cos(angle);
    const y0b = cy + (r0 + offset) * Math.sin(angle);
    const x1b = cx + (r1 + offset) * Math.cos(angle);
    const y1b = cy + (r1 + offset) * Math.sin(angle);

    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.moveTo(x0b, y0b);
    ctx.lineTo(x1b, y1b);
    ctx.stroke();

    if (value > 0.65 && Math.random() < value * 0.35) {
      particles.push({
        angle,
        radius: innerRadius + barLen + 6,
        alpha: 0.9,
        speed: 18 + value * 35
      });
    }
  }

  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.radius += p.speed * 0.016;
    p.alpha -= 0.02;

    if (p.alpha <= 0) {
      particles.splice(i, 1);
      continue;
    }

    const px = cx + p.radius * Math.cos(p.angle);
    const py = cy + p.radius * Math.sin(p.angle);

    ctx.beginPath();
    ctx.fillStyle = `rgba(191, 219, 254, ${p.alpha})`;
    ctx.arc(px, py, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.shadowBlur = 0;
}

/* ============================================
   INIT GERAL
============================================ */
document.addEventListener("DOMContentLoaded", () => {
  initClock();

  if (document.getElementById("searchInput")) {
    initSearchPage();
  }
  if (document.getElementById("audio")) {
    initPlayerPage();
  }
});
