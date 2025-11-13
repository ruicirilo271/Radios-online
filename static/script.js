/* ==========================================================
   RADIO SEARCH + PLAYER NEON — SCRIPT COMPLETO
   Feito para Rui · Compatível com Vercel
========================================================== */

/* ==========================================================
   PÁGINA DE PESQUISA
========================================================== */
function initSearchPage() {
  const input = document.getElementById("searchInput");
  const status = document.getElementById("searchStatus");
  const resultsBox = document.getElementById("resultsBox");

  const btnTop100 = document.getElementById("btnTop100");
  const btnGenres = document.getElementById("btnGenres");
  const btnCountries = document.getElementById("btnCountries");

  if (!input) return; // Não está na página de pesquisa

  /* -------------------------
     Mostrar resultados
  ------------------------- */
  async function procurarRadios(q) {
    status.textContent = "A procurar…";

    const resp = await fetch(`/api/search_all?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    resultsBox.innerHTML = "";

    if (!data.ok || data.radios.length === 0) {
      status.textContent = "Nenhuma rádio encontrada";
      return;
    }

    status.textContent = `${data.radios.length} resultados encontrados`;

    data.radios.forEach(r => {
      const div = document.createElement("div");
      div.className = "result-item";
      div.innerHTML = `
        <strong>${r.name}</strong>
        <span class="country">${r.country || ""}</span>
        <button class="btn small" onclick="location.href='/radio/${r.id}'">▶ Ouvir</button>
      `;
      resultsBox.appendChild(div);
    });
  }

  /* -------------------------
     Pesquisa em tempo-real
  ------------------------- */
  input.addEventListener("input", () => {
    const q = input.value.trim();
    if (q.length < 2) {
      resultsBox.innerHTML = "";
      status.textContent = "";
      return;
    }
    procurarRadios(q);
  });

  /* -------------------------
     TOP 100
  ------------------------- */
  btnTop100?.addEventListener("click", async () => {
    status.textContent = "A carregar Top 100…";
    const resp = await fetch("/api/top100");
    const data = await resp.json();
    resultsBox.innerHTML = "";

    data.radios.forEach(r => {
      const div = document.createElement("div");
      div.className = "result-item";
      div.innerHTML = `
        <strong>${r.name}</strong>
        <span class="country">${r.country}</span>
        <button class="btn small" onclick="location.href='/radio/${r.id}'">▶ Ouvir</button>
      `;
      resultsBox.appendChild(div);
    });

    status.textContent = "Top 100 carregado.";
  });

  /* -------------------------
     GÉNEROS
  ------------------------- */
  btnGenres?.addEventListener("click", async () => {
    status.textContent = "A carregar géneros…";
    const resp = await fetch("/api/genres");
    const data = await resp.json();
    resultsBox.innerHTML = "";

    data.list.forEach(g => {
      const div = document.createElement("div");
      div.className = "result-item";
      div.innerHTML = `
        <strong>${g}</strong>
        <button class="btn small" onclick="procurarRadios('${g}')">Pesquisar</button>
      `;
      resultsBox.appendChild(div);
    });

    status.textContent = "Géneros carregados.";
  });

  /* -------------------------
     PAÍSES
  ------------------------- */
  btnCountries?.addEventListener("click", async () => {
    status.textContent = "A carregar países…";
    const resp = await fetch("/api/countries");
    const data = await resp.json();
    resultsBox.innerHTML = "";

    data.list.forEach(c => {
      const div = document.createElement("div");
      div.className = "result-item";
      div.innerHTML = `
        <strong>${c}</strong>
        <button class="btn small" onclick="procurarRadios('${c}')">Pesquisar</button>
      `;
      resultsBox.appendChild(div);
    });

    status.textContent = "Países carregados.";
  });
}

/* ==========================================================
   EQUALIZER CIRCULAR
========================================================== */
function iniciarEQ(audio, canvas, ctx, coverFrame) {
  if (!audio) return;

  let audioCtx = new AudioContext();
  let analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;

  const source = audioCtx.createMediaElementSource(audio);
  source.connect(analyser);
  source.connect(audioCtx.destination);

  let dataArray = new Uint8Array(analyser.frequencyBinCount);
  let cx = canvas.width / 2;
  let cy = canvas.height / 2;
  let radius = canvas.width / 2 - 4;

  function desenhar() {
    requestAnimationFrame(desenhar);

    analyser.getByteFrequencyData(dataArray);

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (let i = 0; i < dataArray.length; i++) {
      let angle = (i / dataArray.length) * Math.PI * 2;

      let barHeight = (dataArray[i] / 255) * 45 + 10;

      let x1 = cx + Math.cos(angle) * radius;
      let y1 = cy + Math.sin(angle) * radius;

      let x2 = cx + Math.cos(angle) * (radius + barHeight);
      let y2 = cy + Math.sin(angle) * (radius + barHeight);

      ctx.strokeStyle = "#22D3EE";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }

  desenhar();
}

/* ==========================================================
   PLAYER
========================================================== */
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

  if (!audio) return; // estamos na página de pesquisa

  let isPlaying = false;
  let lastTime = 0;

  /* -------------------------
     Função de Reconexão
  ------------------------- */
  function reconnect(reason = "") {
    console.log("🔁 Reconectar stream:", reason);
    statusText.textContent = "A reconectar…";

    const pos = audio.currentTime;

    audio.src = `/proxy/${RADIO_ID}?t=${Date.now()}`;
    audio.load();
    audio
      .play()
      .then(() => {
        isPlaying = true;
        statusText.textContent = "A reproduzir…";
        coverFrame.classList.add("spin");
        iniciarEQ(audio, eqCanvas, ctx, coverFrame);
        audio.currentTime = pos;
      })
      .catch(err => console.log("Falhou:", err));
  }

  /* -------------------------
     Botão Play
  ------------------------- */
  btnPlayPause.addEventListener("click", () => {
    if (!isPlaying) {
      audio.src = `/proxy/${RADIO_ID}`;
      audio.load();
      audio
        .play()
        .then(() => {
          isPlaying = true;
          btnPlayPause.textContent = "⏸ Pausar";
          statusText.textContent = "A reproduzir…";
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

  /* -------------------------
     Eventos críticos → reconectar
  ------------------------- */
  ["error", "stalled", "abort", "waiting", "ended"].forEach(ev => {
    audio.addEventListener(ev, () => reconnect("Evento: " + ev));
  });

  /* -------------------------
     Heartbeat (20s)
  ------------------------- */
  setInterval(() => {
    if (!isPlaying) return;

    if (audio.currentTime === lastTime) {
      reconnect("Heartbeat");
    }

    lastTime = audio.currentTime;
  }, 20000);

  /* -------------------------
     FailSafe 4 minutos
  ------------------------- */
  setInterval(() => {
    if (isPlaying) reconnect("Failsafe 4m");
  }, 240000);

  /* -------------------------
     NOW PLAYING
  ------------------------- */
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
      console.error(err);
    }
  }

  /* -------------------------
     CAPA
  ------------------------- */
  async function carregarCapa(artist, song) {
    const resp = await fetch(`/api/cover?artist=${encodeURIComponent(artist)}&song=${encodeURIComponent(song)}`);
    const data = await resp.json();
    coverImg.src = data.cover || "/static/default_cover.png";
  }

  /* -------------------------
     HISTÓRICO
  ------------------------- */
  async function carregarHistorico() {
    const resp = await fetch(`/api/history?station=${RADIO_ID}`);
    const data = await resp.json();

    historyList.innerHTML = "";
    data.tracks.forEach(t => {
      const li = document.createElement("li");
      li.textContent = `${t.time} — ${t.artist} - ${t.song}`;
      historyList.appendChild(li);
    });
  }

  btnReload.addEventListener("click", atualizarMusica);
  setInterval(atualizarMusica, 12000);
  atualizarMusica();
}

/* ==========================================================
   AUTO-INIT
========================================================== */
document.addEventListener("DOMContentLoaded", () => {
  initSearchPage();
  initPlayerPage();
});
