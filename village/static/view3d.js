// Blocky 3D view of the village, drawn with three.js.
// World x -> three x, world y -> three z, block height z -> three y.
(function () {
  const AGENT_COLORS = ["#f2b84b", "#5bc0eb", "#e86a92", "#9bc53d", "#c38dff", "#ff8c42", "#4ce0b3", "#f25f5c", "#ffe066", "#70a1ff"];
  let T = null;   // everything three.js, created on first use

  function hash(x, y, k = 0) {
    let h = (x * 374761393 + y * 668265263 + k * 2147483647) | 0;
    h = (h ^ (h >>> 13)) * 1274126177;
    return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
  }

  // A 16x16 texture with a darker rim and speckles: the "block" look.
  function blockTexture() {
    const c = document.createElement("canvas");
    c.width = c.height = 16;
    const g = c.getContext("2d");
    const img = g.createImageData(16, 16);
    for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) {
      const edge = x === 0 || y === 0 || x === 15 || y === 15;
      const v = edge ? 170 : 225 + Math.floor(hash(x, y, 7) * 30);
      const i = (y * 16 + x) * 4;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(c);
    tex.magFilter = THREE.NearestFilter;
    tex.minFilter = THREE.NearestFilter;
    return tex;
  }

  function init() {
    if (T) return T;
    const wrap = document.getElementById("mapwrap");
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.domElement.id = "map3d";
    wrap.insertBefore(renderer.domElement, document.getElementById("labels"));

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 600);
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI * 0.47;
    controls.minDistance = 4;
    controls.maxDistance = 140;

    const hemi = new THREE.HemisphereLight(0xe8f4ff, 0x4a5a3a, 0.85);
    const sun = new THREE.DirectionalLight(0xfff4e0, 0.75);
    sun.position.set(-30, 60, 25);
    scene.add(hemi, sun);

    const tex = blockTexture();
    const lit = new THREE.MeshLambertMaterial({ map: tex });
    const glow = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const roofGeo = new THREE.ConeGeometry(0.78, 0.55, 4);
    roofGeo.rotateY(Math.PI / 4);
    const box = new THREE.BoxGeometry(1, 1, 1);

    const make = (geo, mat, n) => {
      const m = new THREE.InstancedMesh(geo, mat, n);
      m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      m.setColorAt(0, new THREE.Color());
      m.userData.capacity = n;
      scene.add(m);
      return m;
    };
    T = {
      renderer, scene, camera, controls, hemi, sun, wrap,
      boxes: make(box, lit, 60000), roofs: make(roofGeo, lit, 3000), glows: make(box, glow, 3000),
      info: [], labels: [], dummy: new THREE.Object3D(), color: new THREE.Color(),
      size: null, visible: false, frame: null,
    };
    let down = null;
    renderer.domElement.addEventListener("pointerdown", e => { down = [e.clientX, e.clientY]; });
    renderer.domElement.addEventListener("click", e => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;   // that was a drag
      pick(e);
    });
    window.addEventListener("resize", resize);
    animate();
    return T;
  }

  function put(mesh, counter, x, y, z, sx, sy, sz, color, info) {
    // (x, y) is the tile, z the height of the shape's bottom.
    const i = counter.n++;
    if (i >= mesh.userData.capacity) return;
    const d = T.dummy;
    d.position.set(x - T.size[0] / 2 + 0.5, z + sy / 2, y - T.size[1] / 2 + 0.5);
    d.scale.set(sx, sy, sz);
    d.rotation.set(0, 0, 0);
    d.updateMatrix();
    mesh.setMatrixAt(i, d.matrix);
    mesh.setColorAt(i, T.color.set(color));
    if (mesh === T.boxes) T.info[i] = info;
  }

  function shade(hex, amount) {
    const c = new THREE.Color(hex);
    c.offsetHSL(0, 0, amount);
    return c.getHex();
  }

  function build(f) {
    const B = { n: 0 }, R = { n: 0 }, G = { n: 0 };
    const box = (x, y, z, sx, sy, sz, col, info = [x, y]) => put(T.boxes, B, x, y, z, sx, sy, sz, col, info);
    T.info = [];
    const blocked = new Set((f.blocks || []).filter(b => b[2] === 1).map(b => b[0] + "," + b[1]));

    for (let y = 0; y < f.height; y++) {
      const row = f.terrain[y];
      for (let x = 0; x < f.width; x++) {
        const c = row[x], r = hash(x, y);
        if (c === "~") { box(x, y, -1, 1, 0.75, 1, shade(0x3b6fa8, (r - 0.5) * 0.04)); continue; }
        if (c === "^") {
          const h = 1 + Math.floor(r * 2);
          box(x, y, -1, 1, 1, 1, 0x7f7f86);
          for (let k = 0; k < h; k++) box(x, y, k, 1, 1, 1, shade(0x8e8e95, (hash(x, y, k) - 0.5) * 0.12));
          continue;
        }
        const grass = c === "T" ? 0x4c8a34 : 0x5f9e3c;
        box(x, y, -1, 1, 1, 1, shade(grass, (r - 0.5) * 0.08));
        if (c === "T") {
          const h = 1 + r * 0.6;
          box(x, y, 0, 0.28, h, 0.28, 0x6b4a2b);
          box(x, y, h, 0.95, 0.85, 0.95, shade(0x2f6b2a, (hash(x, y, 3) - 0.5) * 0.1));
          box(x, y, h + 0.85, 0.55, 0.4, 0.55, shade(0x357a2f, (hash(x, y, 4) - 0.5) * 0.1));
        } else if (c === "*" && !blocked.has(x + "," + y)) {
          box(x, y, 0, 0.55, 0.4, 0.55, 0x3f7f2a);
          for (const [dx, dz, k] of [[-0.15, -0.1, 1], [0.15, 0.05, 2], [0, 0.17, 3]])
            box(x + dx, y + dz, 0.32 + hash(x, y, k) * 0.08, 0.13, 0.13, 0.13, 0xd6336c, [x, y]);
        }
      }
    }

    for (const s of f.structures) {
      const { x, y } = s;
      switch (s.kind) {
        case "wall": box(x, y, 0, 1, 1, 1, 0x7d7d84); box(x, y, 1, 1, 1, 1, 0x86868d); break;
        case "path": box(x, y, 0, 1, 0.08, 1, 0xb7a37a); break;
        case "bridge":
          box(x, y, -0.15, 1, 0.15, 1, 0x9c7a4c);
          box(x, y - 0.45, 0, 1, 0.3, 0.08, 0x7a5a32); box(x, y + 0.45, 0, 1, 0.3, 0.08, 0x7a5a32);
          break;
        case "house":
          box(x, y, 0, 0.9, 0.85, 0.9, 0xc69157);
          box(x, y + 0.45, 0, 0.28, 0.5, 0.03, 0x5a3a1f);
          box(x + 0.25, y + 0.45, 0.45, 0.18, 0.18, 0.03, 0x9fd3ff);
          put(T.roofs, R, x, y, 0.85, 1.25, 1, 1.25, 0x9b3d2c);
          break;
        case "farm":
          box(x, y, 0, 0.95, 0.12, 0.95, 0x6b4a2b);
          for (const [dx, dz] of [[-0.25, -0.25], [0.25, -0.25], [-0.25, 0.25], [0.25, 0.25]])
            box(x + dx, y + dz, 0.12, 0.16, 0.3, 0.16, 0x8bc34a, [x, y]);
          break;
        case "chest":
          box(x, y, 0, 0.6, 0.42, 0.45, 0x8a5a2b);
          box(x, y + 0.23, 0.18, 0.1, 0.1, 0.02, 0xd4af37);
          break;
        case "campfire":
          box(x, y, 0, 0.75, 0.12, 0.16, 0x5a3a1f); box(x, y, 0, 0.16, 0.12, 0.75, 0x5a3a1f);
          for (const [h, w, col] of [[0.1, 0.32, 0xff6a1a], [0.3, 0.2, 0xffb43a]]) put(T.glows, G, x, y, h, w, 0.25, w, col);
          break;
        case "sign":
          box(x, y, 0, 0.1, 0.65, 0.1, 0x6b4a2b);
          box(x, y, 0.55, 0.65, 0.36, 0.07, 0xd9c48b);
          break;
        default: {   // "other": something a being invented
          const total = Object.values(s.materials || {}).reduce((a, b) => a + b, 0) || 3;
          const h = Math.min(4, 0.8 + total / 3);
          box(x, y, 0, 0.7, h, 0.7, 0x9b8fb5);
          put(T.glows, G, x, y, h, 0.3, 0.3, 0.3, 0xc38dff);
        }
      }
    }

    for (const [x, y, z, m] of f.blocks || []) {
      const base = m ? 0x9c9ca3 : 0xb8864b;
      box(x, y, z - 1, 1, 1, 1, shade(base, (hash(x, y, z) - 0.5) * 0.1));
    }

    T.labels.forEach(l => l.el.remove());
    T.labels = [];
    const layer = document.getElementById("labels");
    for (const a of f.agents) {
      const col = AGENT_COLORS[(a.id - 1) % AGENT_COLORS.length];
      box(a.x - 0.1, a.y, 0, 0.16, 0.45, 0.22, 0x3a4a7a); box(a.x + 0.1, a.y, 0, 0.16, 0.45, 0.22, 0x3a4a7a);
      box(a.x, a.y, 0.45, 0.48, 0.55, 0.28, col);
      box(a.x, a.y, 1.0, 0.38, 0.38, 0.38, 0xe3b58c);
      box(a.x, a.y, 1.32, 0.4, 0.1, 0.4, shade(col, -0.25));
      const el = document.createElement("span");
      el.textContent = a.name.startsWith("unnamed") ? `#${a.id}` : a.name;
      layer.appendChild(el);
      T.labels.push({ el, pos: new THREE.Vector3(a.x - f.width / 2 + 0.5, 1.9, a.y - f.height / 2 + 0.5) });
    }

    for (const [mesh, ctr] of [[T.boxes, B], [T.roofs, R], [T.glows, G]]) {
      mesh.count = Math.min(ctr.n, mesh.userData.capacity);
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }

    const night = f.night;
    T.scene.background = new THREE.Color(night ? 0x0b1430 : 0x9fd0ff);
    T.scene.fog = new THREE.Fog(night ? 0x0b1430 : 0x9fd0ff, 60, 160);
    T.hemi.intensity = night ? 0.3 : 0.85;
    T.sun.intensity = night ? 0.12 : 0.75;
  }

  function resize() {
    if (!T || !T.visible) return;
    const narrow = window.innerWidth <= 860;
    const w = T.wrap.clientWidth - 24;
    const h = narrow ? Math.round(Math.min(window.innerHeight * 0.6, w * 1.1)) : T.wrap.clientHeight - 24;
    T.renderer.setSize(w, Math.max(240, h));
    T.camera.aspect = w / Math.max(240, h);
    T.camera.updateProjectionMatrix();
  }

  function animate() {
    requestAnimationFrame(animate);
    if (!T.visible) return;
    T.controls.update();
    T.renderer.render(T.scene, T.camera);
    const w = T.renderer.domElement.clientWidth, h = T.renderer.domElement.clientHeight;
    const v = new THREE.Vector3();
    for (const l of T.labels) {
      v.copy(l.pos).project(T.camera);
      const off = v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1;
      l.el.style.display = off ? "none" : "block";
      l.el.style.left = (12 + (v.x + 1) / 2 * w) + "px";
      l.el.style.top = (12 + (1 - v.y) / 2 * h) + "px";
    }
  }

  function pick(e) {
    const r = T.renderer.domElement.getBoundingClientRect();
    const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(p, T.camera);
    const hit = ray.intersectObject(T.boxes)[0];
    const info = hit && T.info[hit.instanceId];
    window.showTip(info ? info[0] : -1, info ? info[1] : -1, e.clientX, e.clientY);
  }

  window.Village3D = {
    ok() {
      if (!window.THREE || !THREE.OrbitControls) return false;
      try { init(); return true; } catch (err) { console.warn("3D view unavailable", err); return false; }
    },
    show(f) {
      const first = !T.size || T.size[0] !== f.width || T.size[1] !== f.height;
      T.size = [f.width, f.height];
      if (!T.visible) { T.visible = true; T.renderer.domElement.style.display = "block"; document.getElementById("labels").style.display = "block"; }
      resize();
      if (first) {
        const span = Math.max(f.width, f.height);
        T.camera.position.set(0, span * 0.62, span * 0.78);
        T.controls.target.set(0, 0, 0);
        T.controls.update();
      }
      if (T.frame !== f) { T.frame = f; build(f); }
    },
    focus(x, y, dist = 14) {
      if (!T || !T.size) return;
      const target = new THREE.Vector3(x - T.size[0] / 2 + 0.5, 0.5, y - T.size[1] / 2 + 0.5);
      const dir = T.camera.position.clone().sub(T.controls.target).normalize();
      T.controls.target.copy(target);
      T.camera.position.copy(target).add(dir.multiplyScalar(dist));
      T.controls.update();
    },
    hide() {
      if (!T) return;
      T.visible = false;
      T.renderer.domElement.style.display = "none";
      document.getElementById("labels").style.display = "none";
    },
  };
})();
