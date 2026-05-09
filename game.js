const canvas = document.querySelector("#game");
const ctx = canvas.getContext("2d");
const scoreEl = document.querySelector("#score");
const comboEl = document.querySelector("#combo");
const shieldEl = document.querySelector("#shield");
const startButton = document.querySelector("#start");
const touchButtons = document.querySelectorAll("[data-key]");
const dashButton = document.querySelector("[data-dash]");

const keys = new Set();
const rand = (min, max) => Math.random() * (max - min) + min;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

let state;
let lastTime = 0;
let animationId = 0;

function createState() {
  const { w, h } = worldSize();
  return {
    running: true,
    over: false,
    time: 0,
    score: 0,
    combo: 1,
    shield: 100,
    shake: 0,
    spawnTimer: 0,
    coreTimer: 0,
    dashTimer: 0,
    messageTimer: 2.4,
    player: {
      x: w / 2,
      y: h / 2,
      r: 13,
      speed: 250,
      vx: 0,
      vy: 0,
      trail: [],
    },
    enemies: [],
    cores: [],
    particles: [],
    stars: Array.from({ length: 120 }, () => ({
      x: rand(0, canvas.width),
      y: rand(0, canvas.height),
      r: rand(0.5, 1.8),
      a: rand(0.18, 0.78),
    })),
  };
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const scale = window.devicePixelRatio || 1;
  canvas.width = Math.floor(rect.width * scale);
  canvas.height = Math.floor(rect.height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
}

function worldSize() {
  const rect = canvas.getBoundingClientRect();
  return { w: rect.width, h: rect.height };
}

function spawnEnemy() {
  const { w, h } = worldSize();
  const edge = Math.floor(rand(0, 4));
  const pos = [
    { x: rand(0, w), y: -24 },
    { x: w + 24, y: rand(0, h) },
    { x: rand(0, w), y: h + 24 },
    { x: -24, y: rand(0, h) },
  ][edge];

  state.enemies.push({
    ...pos,
    r: rand(12, 19),
    speed: rand(76, 130) + state.time * 1.8,
    turn: rand(0.85, 1.22),
    hue: Math.random() > 0.42 ? "#ff4f8b" : "#ffd166",
  });
}

function spawnCore() {
  const { w, h } = worldSize();
  state.cores.push({
    x: rand(36, w - 36),
    y: rand(64, h - 64),
    r: rand(8, 12),
    pulse: rand(0, Math.PI * 2),
    value: 100,
  });
}

function burst(x, y, color, count = 18) {
  for (let i = 0; i < count; i += 1) {
    const angle = rand(0, Math.PI * 2);
    const speed = rand(40, 230);
    state.particles.push({
      x,
      y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      life: rand(0.28, 0.72),
      maxLife: 0.72,
      r: rand(1.5, 4.2),
      color,
    });
  }
}

function startGame() {
  resizeCanvas();
  state = createState();
  startButton.blur();
  startButton.classList.add("is-hidden");
  lastTime = performance.now();
  cancelAnimationFrame(animationId);
  animationId = requestAnimationFrame(loop);
}

function dash() {
  if (state?.running && state.dashTimer <= 0) {
    state.dashTimer = 0.18;
    state.shield = Math.max(0, state.shield - 1);
  }
}

function movePlayer(dt) {
  const p = state.player;
  let ax = 0;
  let ay = 0;
  if (keys.has("arrowleft") || keys.has("a")) ax -= 1;
  if (keys.has("arrowright") || keys.has("d")) ax += 1;
  if (keys.has("arrowup") || keys.has("w")) ay -= 1;
  if (keys.has("arrowdown") || keys.has("s")) ay += 1;

  const length = Math.hypot(ax, ay) || 1;
  const dashing = state.dashTimer > 0;
  const speed = p.speed * (dashing ? 2.55 : 1);
  p.vx = (ax / length) * speed;
  p.vy = (ay / length) * speed;
  p.x += p.vx * dt;
  p.y += p.vy * dt;

  const { w, h } = worldSize();
  p.x = clamp(p.x, p.r + 2, w - p.r - 2);
  p.y = clamp(p.y, p.r + 2, h - p.r - 2);
  p.trail.unshift({ x: p.x, y: p.y, life: 1 });
  p.trail = p.trail.slice(0, dashing ? 22 : 14);
  p.trail.forEach((point) => {
    point.life -= dt * 3.8;
  });
}

function update(dt) {
  state.time += dt;
  state.spawnTimer -= dt;
  state.coreTimer -= dt;
  state.dashTimer = Math.max(0, state.dashTimer - dt);
  state.shake = Math.max(0, state.shake - dt * 18);
  state.messageTimer = Math.max(0, state.messageTimer - dt);

  if (state.spawnTimer <= 0) {
    spawnEnemy();
    state.spawnTimer = Math.max(0.32, 1.15 - state.time * 0.012);
  }
  if (state.coreTimer <= 0 || state.cores.length < 2) {
    spawnCore();
    state.coreTimer = rand(0.72, 1.25);
  }

  movePlayer(dt);

  const player = state.player;
  state.enemies.forEach((enemy) => {
    const angle = Math.atan2(player.y - enemy.y, player.x - enemy.x);
    enemy.x += Math.cos(angle) * enemy.speed * enemy.turn * dt;
    enemy.y += Math.sin(angle) * enemy.speed * enemy.turn * dt;
  });

  state.cores = state.cores.filter((core) => {
    core.pulse += dt * 5;
    if (distance(player, core) < player.r + core.r + 5) {
      state.score += Math.round(core.value * state.combo);
      state.combo = Math.min(9, state.combo + 0.25);
      state.shield = Math.min(100, state.shield + 4);
      burst(core.x, core.y, "#37f4ff", 24);
      return false;
    }
    return true;
  });

  state.enemies = state.enemies.filter((enemy) => {
    if (distance(player, enemy) < player.r + enemy.r) {
      const damage = state.dashTimer > 0 ? 4 : 20;
      state.shield -= damage;
      state.combo = 1;
      state.shake = 8;
      burst(enemy.x, enemy.y, enemy.hue, 22);
      if (state.shield <= 0) endGame();
      return false;
    }
    return true;
  });

  state.particles = state.particles.filter((particle) => {
    particle.life -= dt;
    particle.x += particle.vx * dt;
    particle.y += particle.vy * dt;
    particle.vx *= 0.98;
    particle.vy *= 0.98;
    return particle.life > 0;
  });

  state.combo = Math.max(1, state.combo - dt * 0.055);
  scoreEl.textContent = String(Math.floor(state.score));
  comboEl.textContent = `x${state.combo.toFixed(1)}`;
  shieldEl.textContent = `${Math.max(0, Math.ceil(state.shield))}%`;
}

function endGame() {
  state.over = true;
  state.running = false;
  startButton.textContent = "שחק שוב";
  startButton.classList.remove("is-hidden");
}

function drawBackground(w, h) {
  ctx.clearRect(0, 0, w, h);
  const grd = ctx.createRadialGradient(w * 0.5, h * 0.5, 40, w * 0.5, h * 0.5, Math.max(w, h));
  grd.addColorStop(0, "#10243a");
  grd.addColorStop(0.55, "#081423");
  grd.addColorStop(1, "#060912");
  ctx.fillStyle = grd;
  ctx.fillRect(0, 0, w, h);

  ctx.save();
  ctx.globalAlpha = 0.28;
  ctx.strokeStyle = "#37f4ff";
  ctx.lineWidth = 1;
  for (let x = -60; x < w + 60; x += 48) {
    ctx.beginPath();
    ctx.moveTo(x + ((state.time * 12) % 48), 0);
    ctx.lineTo(x - 180 + ((state.time * 12) % 48), h);
    ctx.stroke();
  }
  ctx.restore();

  state.stars.forEach((star) => {
    ctx.globalAlpha = star.a + Math.sin(state.time * 2 + star.x) * 0.12;
    ctx.fillStyle = "#d9fbff";
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.globalAlpha = 1;
}

function drawPlayer() {
  const p = state.player;
  p.trail.forEach((point, index) => {
    ctx.globalAlpha = Math.max(0, point.life) * (1 - index / p.trail.length) * 0.5;
    ctx.fillStyle = "#37f4ff";
    ctx.beginPath();
    ctx.arc(point.x, point.y, p.r + 8 - index * 0.35, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.globalAlpha = 1;

  ctx.shadowBlur = state.dashTimer > 0 ? 30 : 18;
  ctx.shadowColor = "#37f4ff";
  ctx.fillStyle = "#eaffff";
  ctx.beginPath();
  ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#37f4ff";
  ctx.lineWidth = 4;
  ctx.stroke();
  ctx.shadowBlur = 0;
}

function drawEntities() {
  state.cores.forEach((core) => {
    const pulse = Math.sin(core.pulse) * 4;
    ctx.shadowBlur = 22;
    ctx.shadowColor = "#90ff72";
    ctx.fillStyle = "#90ff72";
    ctx.beginPath();
    ctx.arc(core.x, core.y, core.r + pulse, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = 2;
    ctx.stroke();
  });

  state.enemies.forEach((enemy) => {
    ctx.save();
    ctx.translate(enemy.x, enemy.y);
    ctx.rotate(state.time * 2);
    ctx.shadowBlur = 18;
    ctx.shadowColor = enemy.hue;
    ctx.fillStyle = enemy.hue;
    ctx.beginPath();
    for (let i = 0; i < 6; i += 1) {
      const angle = (Math.PI * 2 * i) / 6;
      const radius = i % 2 ? enemy.r * 0.68 : enemy.r;
      const x = Math.cos(angle) * radius;
      const y = Math.sin(angle) * radius;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  });

  state.particles.forEach((particle) => {
    ctx.globalAlpha = clamp(particle.life / particle.maxLife, 0, 1);
    ctx.fillStyle = particle.color;
    ctx.beginPath();
    ctx.arc(particle.x, particle.y, particle.r, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.globalAlpha = 1;
}

function drawMessage(w, h) {
  if (state.messageTimer <= 0 && !state.over) return;
  const narrow = w < 520;
  const title = state.over ? "הקרע ניצח" : narrow ? "אספו ליבות" : "אספו ליבות. Space לדש.";
  const subtitle = state.over
    ? `ניקוד סופי: ${Math.floor(state.score)}`
    : narrow
      ? "Dash לדילוג מהיר"
      : "כל ליבה מגדילה את המכפיל. פגיעה מאפסת אותו.";
  ctx.save();
  ctx.textAlign = "center";
  ctx.fillStyle = "#f7fbff";
  ctx.shadowBlur = 24;
  ctx.shadowColor = "#37f4ff";
  ctx.font = `800 ${narrow ? 30 : 36}px Segoe UI, Arial`;
  ctx.fillText(title, w / 2, h / 2 - 34);
  ctx.font = `600 ${narrow ? 16 : 18}px Segoe UI, Arial`;
  ctx.shadowBlur = 0;
  ctx.fillStyle = "rgba(247, 251, 255, 0.76)";
  ctx.fillText(subtitle, w / 2, h / 2 + 4);
  ctx.restore();
}

function draw() {
  const { w, h } = worldSize();
  ctx.save();
  if (state.shake > 0) {
    ctx.translate(rand(-state.shake, state.shake), rand(-state.shake, state.shake));
  }
  drawBackground(w, h);
  drawEntities();
  drawPlayer();
  drawMessage(w, h);
  ctx.restore();
}

function loop(now) {
  const dt = Math.min(0.032, (now - lastTime) / 1000);
  lastTime = now;
  if (state.running) update(dt);
  draw();
  animationId = requestAnimationFrame(loop);
}

window.addEventListener("keydown", (event) => {
  keys.add(event.key.toLowerCase());
  if (event.code === "Space") dash();
});

window.addEventListener("keyup", (event) => {
  keys.delete(event.key.toLowerCase());
});

window.addEventListener("resize", () => {
  const oldState = state;
  resizeCanvas();
  if (oldState) {
    const { w, h } = worldSize();
    oldState.player.x = clamp(oldState.player.x, 20, w - 20);
    oldState.player.y = clamp(oldState.player.y, 20, h - 20);
  }
});

startButton.addEventListener("click", startGame);

touchButtons.forEach((button) => {
  const key = button.dataset.key;
  const press = (event) => {
    event.preventDefault();
    keys.add(key);
    button.classList.add("is-pressed");
  };
  const release = (event) => {
    event.preventDefault();
    keys.delete(key);
    button.classList.remove("is-pressed");
  };
  button.addEventListener("pointerdown", press);
  button.addEventListener("pointerup", release);
  button.addEventListener("pointercancel", release);
  button.addEventListener("pointerleave", release);
});

if (dashButton) {
  dashButton.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    dash();
    dashButton.classList.add("is-pressed");
  });

  dashButton.addEventListener("pointerup", () => {
    dashButton.classList.remove("is-pressed");
  });

  dashButton.addEventListener("pointercancel", () => {
    dashButton.classList.remove("is-pressed");
  });
}

resizeCanvas();
state = createState();
draw();
