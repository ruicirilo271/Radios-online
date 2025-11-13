/* ==========================
   SELETORES
========================== */
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

/* ==========================
   PLAYER
========================== */
btnPlayPause.addEventListener("click", () => {
  if (!isPlaying) {
    statusText.textContent = "A iniciar stream...";

    audio.src = `/proxy/${RADIO_ID}`;
    audio.load();

    audio.play().then(() => {
      isPlaying = true;
      btnPlayPause.textContent = "⏸ Pausar";
      statusText.textContent = "A reproduzir...";

      // vinil começa a girar
      coverFrame.classList.add("spin");

      iniciarEQ();
    }).catch(err => {
      console.log("⚠️ Som bloqueado:", err);
      statusText.textContent = "Clique novamente para iniciar o áudio.";
    });
  } else {
    audio.pause();
    isPlaying = false;
    btnPlayPause.textContent = "▶ Reproduzir";
    statusText.textContent = "Pausado.";

    coverFrame.classList.remove("spin");
  }
});

audio.addEventListener("pause", () => {
  isPlaying = false;
  btnPlayPause.textContent = "▶ Reproduzir";
  coverFrame.classList.remove("spin");
});

/* auto-reconnect se stream parar inesperadamente */
function tentarReconectar() {
  if (!isPlaying) return;
  console.log("🔁 Tentativa de reconectar stream...");
  audio.src = `/proxy/${RADIO_ID}`;
  audio.load();
  audio.play().catch(err => console.log("Erro ao reconectar:", err));
}

audio.addEventListener("error", tentarReconectar);
audio.addEventListener("stalled", tentarReconectar);
audio.addEventListener("ended", tentarReconectar);

/* ==========================
   API NOW PLAYING
========================== */
let ultimoArtist = "";
let ultimoSong = "";

async function atualizarMusica() {
  console.log("📡 CHAMAR /api/nowplaying");

  try {
    const resp = await fetch(`/api/nowplaying?station=${RADIO_ID}`);
    const data = await resp.json();
    console.log("➡️ RESPOSTA:", data);

    if (!data.ok) {
      artistNow.textContent = "Desconhecido";
      songNow.textContent = "Desconhecido";
      return;
    }

    const novoArtist = data.artist || "Desconhecido";
    const novoSong = data.song || "Desconhecido";

    // flash apenas se mudou de música
    if (novoArtist !== ultimoArtist || novoSong !== ultimoSong) {
      const meta = document.querySelector(".track-meta");
      meta.classList.remove("flash");
      // força reflow para reiniciar animação
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
    console.error("❌ ERRO /api/nowplaying:", err);
  }
}

/* ==========================
   API CAPA + CACHE LOCAL
========================== */
async function carregarCapa(artist, song) {
  const a = (artist || "").trim();
  const s = (song || "").trim();

  if (!a || !s || a.toLowerCase() === "desconhecido" && s.toLowerCase() === "desconhecido") {
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
    if (data.cover) {
      localStorage.setItem(key, url);
    }
  } catch (err) {
    console.error("Erro a carregar capa:", err);
    coverImg.src = "/static/default_cover.png";
  }
}

/* ==========================
   HISTÓRICO
========================== */
async function carregarHistorico() {
  const resp = await fetch(`/api/history?station=${RADIO_ID}`);
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
}

/* ==========================
   BOTÃO RECARREGAR
========================== */
btnReload.addEventListener("click", atualizarMusica);

/* ==========================
   EQUALIZER CIRCULAR (vinil)
========================== */
/* ==========================
   EQUALIZER CIRCULAR (vinil – Space Neon)
========================== */
let audioCtx = null;
let analyser = null;
let dataArray = null;
let bufferLength = 0;
let eqAnimId = null;

const particles = [];

function iniciarEQ() {
  if (audioCtx) {
    // se já existe contexto mas está suspenso, retoma
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    return;
  }

  const ACtx = window.AudioContext || window.webkitAudioContext;
  if (!ACtx) {
    console.warn("Web Audio API não disponível.");
    return;
  }

  audioCtx = new ACtx();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 512; // mais detalhe
  bufferLength = analyser.frequencyBinCount;
  dataArray = new Uint8Array(bufferLength);

  const source = audioCtx.createMediaElementSource(audio);
  source.connect(analyser);
  analyser.connect(audioCtx.destination);

  desenharEQCircular();
}

function desenharEQCircular() {
  eqAnimId = requestAnimationFrame(desenharEQCircular);
  if (!analyser || !dataArray) return;

  analyser.getByteFrequencyData(dataArray);

  const w = eqCanvas.width;
  const h = eqCanvas.height;
  const cx = w / 2;
  const cy = h / 2;

  ctx.clearRect(0, 0, w, h);

  const innerRadius = 90;       // raio onde começam as barras
  const maxBarLen   = 42;       // comprimento máximo
  const bars        = bufferLength; // TODAS as barras disponíveis

  const now = performance.now() / 1000; // segundos

  // energia de graves (primeiros bins)
  let bassSum = 0;
  const bassBins = Math.min(40, bufferLength);
  for (let i = 0; i < bassBins; i++) {
    bassSum += dataArray[i] || 0;
  }
  const bassLevel = (bassSum / bassBins) / 255; // 0–1

  // "bounce" visual do vinil via glow
  const glowIntensity = 0.4 + bassLevel * 1.2;
  coverFrame.style.boxShadow =
    `0 0 ${25 + bassLevel * 40}px rgba(56,189,248,${glowIntensity})`;

  // aurora: base hue vai rodando devagar no tempo
  const baseHue = 200 + Math.sin(now * 0.3) * 40;

  // ── BARRAS CIRCULARES (duplas) ──
  for (let i = 0; i < bars; i++) {
    const raw = dataArray[i] || 0;
    const value = raw / 255;               // 0–1
    const barLen = 8 + value * maxBarLen;  // comprimento

    const angle = (i / bars) * Math.PI * 2;

    // posição radial
    const r0 = innerRadius;
    const r1 = innerRadius + barLen;

    const x0 = cx + r0 * Math.cos(angle);
    const y0 = cy + r0 * Math.sin(angle);
    const x1 = cx + r1 * Math.cos(angle);
    const y1 = cy + r1 * Math.sin(angle);

    // cor "space neon" (aurora boreal)
    const hueShift = Math.sin(angle * 2 + now * 0.6) * 30;
    const hue = (baseHue + hueShift + 360) % 360;
    const sat = 85;
    const lightStart = 35;
    const lightEnd   = 70;

    const grad = ctx.createLinearGradient(x0, y0, x1, y1);
    grad.addColorStop(0, `hsla(${hue}, ${sat}%, ${lightStart}%, 0.15)`);
    grad.addColorStop(1, `hsla(${hue}, ${sat}%, ${lightEnd}%, 1)`);

    ctx.lineWidth = 2.3;
    ctx.strokeStyle = grad;
    ctx.shadowBlur = 15;
    ctx.shadowColor = `hsla(${hue}, ${sat}%, ${lightEnd}%, 0.8)`;

    // barra principal
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.stroke();

    // barra extra (dupla) ligeiramente deslocada para dar 3D
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

    // ── PARTÍCULAS ──
    if (value > 0.65 && Math.random() < value * 0.35) {
      particles.push({
        angle,
        radius: innerRadius + barLen + 6,
        alpha: 0.9,
        speed: 18 + value * 35
      });
    }
  }

  // ── DESENHAR PARTÍCULAS ──
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.radius += p.speed * 0.016; // ~velocidade por frame
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

  // reset sombra no fim
  ctx.shadowBlur = 0;
}



/* ==========================
   AUTO ATUALIZAR CADA 12s
========================== */
setInterval(atualizarMusica, 12000);

/* ==========================
   CARREGAR AO ENTRAR
========================== */
document.addEventListener("DOMContentLoaded", () => {
  atualizarMusica();

  // modo mais "dark neon" à noite
  const hora = new Date().getHours();
  if (hora >= 20 || hora < 7) {
    document.body.classList.add("night-mode");
  }
});
