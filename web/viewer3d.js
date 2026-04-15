const STATUS_COLORS = {
  PASS: "#FF7A1A",
  PASS_WITH_WARNINGS: "#FF9B38",
  WARNING: "#FFB14D",
  OUTSIDE_SCOPE: "#8FA4FF",
  WAITING: "#58627D",
};

export class FootingViewer {
  constructor(container) {
    this.container = container;
    this.canvas = document.createElement("canvas");
    this.overlay = document.createElement("div");
    this.overlay.className = "viewer-overlay";
    this.overlay.innerHTML = "<span>Drag to orbit · Scroll to zoom</span><span>Shift + drag to pan</span>";
    this.container.append(this.canvas, this.overlay);
    this.canvas.style.touchAction = "none";
    this.container.style.touchAction = "none";

    this.context = this.canvas.getContext("2d");
    this.rotationX = -0.58;
    this.rotationY = 0.72;
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
    this.result = null;

    this.bindInteractions();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();
  }

  bindInteractions() {
    let dragging = false;
    let startX = 0;
    let startY = 0;
    let startRotX = this.rotationX;
    let startRotY = this.rotationY;
    let startPanX = this.panX;
    let startPanY = this.panY;
    let isPanning = false;

    this.canvas.addEventListener("pointerdown", (event) => {
      dragging = true;
      isPanning = event.shiftKey;
      startX = event.clientX;
      startY = event.clientY;
      startRotX = this.rotationX;
      startRotY = this.rotationY;
      startPanX = this.panX;
      startPanY = this.panY;
      this.canvas.setPointerCapture(event.pointerId);
    });

    this.canvas.addEventListener("pointermove", (event) => {
      if (!dragging) {
        return;
      }

      const deltaX = event.clientX - startX;
      const deltaY = event.clientY - startY;

      if (isPanning) {
        this.panX = startPanX + deltaX;
        this.panY = startPanY + deltaY;
      } else {
        this.rotationY = startRotY - deltaX * 0.008;
        this.rotationX = startRotX + deltaY * 0.006;
      }

      this.render();
    });

    this.canvas.addEventListener("pointerup", (event) => {
      dragging = false;
      this.canvas.releasePointerCapture(event.pointerId);
    });

    const handleWheelZoom = (event) => {
      event.preventDefault();
      event.stopPropagation();

      // Trackpads produce much smaller deltas than a mouse wheel, so scale gently.
      const delta = clamp(event.deltaY, -80, 80);
      const zoomFactor = Math.exp(-delta * 0.0025);
      this.zoom = clamp(this.zoom * zoomFactor, 0.45, 2.8);
      this.render();
    };

    this.canvas.addEventListener("wheel", handleWheelZoom, { passive: false });
    this.container.addEventListener("wheel", handleWheelZoom, { passive: false });

    // Safari trackpad pinch can surface as gesture events instead of wheel events.
    let gestureStartZoom = this.zoom;
    const handleGesture = (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.zoom = clamp(gestureStartZoom * event.scale, 0.45, 2.8);
      this.render();
    };

    this.container.addEventListener(
      "gesturestart",
      (event) => {
        event.preventDefault();
        gestureStartZoom = this.zoom;
      },
      { passive: false }
    );
    this.container.addEventListener("gesturechange", handleGesture, { passive: false });
  }

  resize() {
    const width = this.container.clientWidth || 600;
    const height = this.container.clientHeight || 320;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);

    this.canvas.width = Math.floor(width * pixelRatio);
    this.canvas.height = Math.floor(height * pixelRatio);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    this.render();
  }

  update(result) {
    this.result = result;
    this.render();
  }

  render() {
    const ctx = this.context;
    if (!ctx) {
      return;
    }

    const width = this.canvas.clientWidth || 600;
    const height = this.canvas.clientHeight || 320;
    ctx.clearRect(0, 0, width, height);

    drawBackground(ctx, width, height);

    const status = this.result?.summary?.status || "WAITING";
    const footingWidth = Number(this.result?.recommended_width_ft) || 7.5;
    const footingLength = Number(this.result?.recommended_length_ft) || 7.5;
    const thickness = Number(this.result?.input_data?.footing_thickness_ft) || 1.5;
    const columnWidth = Number(this.result?.input_data?.column_width_ft) || 1.5;
    const columnLength = Number(this.result?.input_data?.column_length_ft) || 1.5;
    const eccentricityX = Number(this.result?.eccentricity_x_ft) || 0;
    const eccentricityY = Number(this.result?.eccentricity_y_ft) || 0;
    const qmin = Number(this.result?.qmin_ksf) || 0;
    const qmax = Number(this.result?.qmax_ksf) || 0;

    const baseScale = clamp(
      Math.min(width / (footingLength + 5), height / (footingWidth + thickness + 6)) * 20,
      22,
      54
    );
    const scene = {
      cx: width * 0.5 + this.panX,
      cy: height * 0.64 + this.panY,
      scale: clamp(baseScale * this.zoom, 12, 180),
      rotX: this.rotationX,
      rotY: this.rotationY,
    };

    const footingColor = STATUS_COLORS[status] || STATUS_COLORS.WAITING;

    const footingFaces = boxFaces({
      center: { x: 0, y: thickness / 2, z: 0 },
      width: footingLength,
      height: thickness,
      depth: footingWidth,
    });

    const columnFaces = boxFaces({
      center: { x: 0, y: thickness + Math.max(2.8, thickness * 2.4) / 2, z: 0 },
      width: columnLength,
      height: Math.max(2.8, thickness * 2.4),
      depth: columnWidth,
    });

    const kernPoints = rectanglePoints(footingLength / 3, footingWidth / 3, thickness + 0.05);
    const loadPoint = { x: eccentricityX, y: thickness + 0.1, z: eccentricityY };
    const centroidPoint = { x: 0, y: thickness + 0.08, z: 0 };

    const drawables = [];

    const footingFaceTints = [0.08, -0.18, 0.02, -0.08, -0.14, -0.12];
    footingFaces.forEach((face, index) => {
      drawables.push({
        depth: averageDepth(face, scene),
        draw: () =>
          drawFace(
            ctx,
            face,
            scene,
            tintHex(footingColor, footingFaceTints[index] ?? -0.1),
            "#FFB26E"
          ),
      });
    });

    const columnFaceColors = ["#D7DEF8", "#495779", "#BBC7EB", "#67769B", "#93A1CA", "#5A6789"];
    columnFaces.forEach((face, index) => {
      drawables.push({
        depth: averageDepth(face, scene),
        draw: () =>
          drawFace(
            ctx,
            face,
            scene,
            columnFaceColors[index] ?? "#5A6789",
            "#DDE7FF"
          ),
      });
    });

    drawables.sort((a, b) => a.depth - b.depth).forEach((item) => item.draw());

    drawPolyline(ctx, [...kernPoints, kernPoints[0]], scene, "#8FA4FF", 2.2, [6, 5]);
    drawPolyline(ctx, [centroidPoint, loadPoint], scene, "#FF8B2A", 2, [5, 5]);
    drawMarker(ctx, centroidPoint, scene, "#FF7A1A", 4.5);
    drawMarker(ctx, loadPoint, scene, "#F6F8FF", 5.5);
    drawLoadArrow(ctx, loadPoint, scene);
    drawPressureBars(ctx, footingLength, footingWidth, thickness, qmin, qmax, scene);
    drawLabels(ctx, footingLength, footingWidth, thickness, eccentricityX, eccentricityY, scene);
  }
}

function drawBackground(ctx, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#0A0F1C");
  gradient.addColorStop(1, "#05070D");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(121, 139, 194, 0.09)";
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 0; y < height; y += 32) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  const glow = ctx.createRadialGradient(width * 0.62, height * 0.22, 12, width * 0.62, height * 0.22, width * 0.38);
  glow.addColorStop(0, "rgba(255, 122, 26, 0.12)");
  glow.addColorStop(1, "rgba(255, 122, 26, 0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.ellipse(width * 0.62, height * 0.22, width * 0.34, height * 0.2, 0, 0, Math.PI * 2);
  ctx.fill();
}

function boxFaces({ center, width, height, depth }) {
  const x = width / 2;
  const y = height / 2;
  const z = depth / 2;

  const p = {
    lbf: { x: center.x - x, y: center.y - y, z: center.z + z },
    rbf: { x: center.x + x, y: center.y - y, z: center.z + z },
    lbb: { x: center.x - x, y: center.y - y, z: center.z - z },
    rbb: { x: center.x + x, y: center.y - y, z: center.z - z },
    ltf: { x: center.x - x, y: center.y + y, z: center.z + z },
    rtf: { x: center.x + x, y: center.y + y, z: center.z + z },
    ltb: { x: center.x - x, y: center.y + y, z: center.z - z },
    rtb: { x: center.x + x, y: center.y + y, z: center.z - z },
  };

  return [
    [p.ltf, p.rtf, p.rtb, p.ltb], // top
    [p.lbf, p.rbf, p.rbb, p.lbb], // bottom
    [p.lbf, p.rbf, p.rtf, p.ltf], // front
    [p.lbb, p.rbb, p.rtb, p.ltb], // back
    [p.lbf, p.lbb, p.ltb, p.ltf], // left
    [p.rbf, p.rbb, p.rtb, p.rtf], // right
  ];
}

function rectanglePoints(width, depth, y) {
  const x = width / 2;
  const z = depth / 2;
  return [
    { x: -x, y, z: z },
    { x: x, y, z: z },
    { x: x, y, z: -z },
    { x: -x, y, z: -z },
  ];
}

function project(point, scene) {
  const cosY = Math.cos(scene.rotY);
  const sinY = Math.sin(scene.rotY);
  const cosX = Math.cos(scene.rotX);
  const sinX = Math.sin(scene.rotX);

  const x1 = point.x * cosY - point.z * sinY;
  const z1 = point.x * sinY + point.z * cosY;
  const y1 = point.y;

  const y2 = y1 * cosX - z1 * sinX;
  const z2 = y1 * sinX + z1 * cosX;

  return {
    x: scene.cx + x1 * scene.scale,
    y: scene.cy - y2 * scene.scale,
    depth: z2,
  };
}

function averageDepth(points, scene) {
  return points.reduce((total, point) => total + project(point, scene).depth, 0) / points.length;
}

function drawFace(ctx, points, scene, fill, stroke) {
  const projected = points.map((point) => project(point, scene));
  ctx.beginPath();
  ctx.moveTo(projected[0].x, projected[0].y);
  projected.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1.3;
  ctx.stroke();
}

function drawPolyline(ctx, points, scene, stroke, width, dash = []) {
  const projected = points.map((point) => project(point, scene));
  ctx.save();
  ctx.setLineDash(dash);
  ctx.beginPath();
  ctx.moveTo(projected[0].x, projected[0].y);
  projected.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
  ctx.strokeStyle = stroke;
  ctx.lineWidth = width;
  ctx.stroke();
  ctx.restore();
}

function drawMarker(ctx, point, scene, fill, radius) {
  const projected = project(point, scene);
  ctx.beginPath();
  ctx.arc(projected.x, projected.y, radius, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.strokeStyle = "rgba(8,20,20,0.72)";
  ctx.lineWidth = 1.2;
  ctx.stroke();
}

function drawLoadArrow(ctx, point, scene) {
  const top = { x: point.x, y: point.y + 2.2, z: point.z };
  const base = { x: point.x, y: point.y + 0.15, z: point.z };
  const pTop = project(top, scene);
  const pBase = project(base, scene);

  ctx.save();
  ctx.strokeStyle = "#FF8B2A";
  ctx.lineWidth = 2.4;
  ctx.beginPath();
  ctx.moveTo(pTop.x, pTop.y);
  ctx.lineTo(pBase.x, pBase.y);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(pBase.x, pBase.y);
  ctx.lineTo(pBase.x - 6, pBase.y - 10);
  ctx.lineTo(pBase.x + 6, pBase.y - 10);
  ctx.closePath();
  ctx.fillStyle = "#FF8B2A";
  ctx.fill();
  ctx.restore();
}

function drawPressureBars(ctx, footingLength, footingWidth, thickness, qmin, qmax, scene) {
  const maxHeight = clamp(qmax * 0.22, 0.25, 2.0);
  const minHeight = clamp(Math.max(qmin, 0) * 0.22, 0.18, 1.6);

  const barA = boxFaces({
    center: { x: footingLength / 2 - 0.45, y: thickness + maxHeight / 2, z: footingWidth / 2 - 0.45 },
    width: 0.22,
    height: maxHeight,
    depth: 0.22,
  });

  const barB = boxFaces({
    center: { x: -footingLength / 2 + 0.45, y: thickness + minHeight / 2, z: -footingWidth / 2 + 0.45 },
    width: 0.22,
    height: minHeight,
    depth: 0.22,
  });

  [...barA, ...barB].forEach((face, index) => {
    drawFace(
      ctx,
      face,
      scene,
      index < 3 ? "rgba(255,122,26,0.34)" : "rgba(143,164,255,0.24)",
      "rgba(221,231,255,0.26)"
    );
  });
}

function drawLabels(ctx, footingLength, footingWidth, thickness, ex, ey, scene) {
  const points = [
    { label: `L ${footingLength.toFixed(2)} ft`, point: { x: footingLength / 2, y: 0, z: footingWidth / 2 + 0.8 } },
    { label: `W ${footingWidth.toFixed(2)} ft`, point: { x: -footingLength / 2 - 0.8, y: 0, z: footingWidth / 2 } },
    { label: `t ${thickness.toFixed(2)} ft`, point: { x: -footingLength / 2 - 0.7, y: thickness, z: -footingWidth / 2 } },
    { label: `ex ${ex.toFixed(2)} ft`, point: { x: ex, y: thickness + 0.42, z: 0 } },
    { label: `ey ${ey.toFixed(2)} ft`, point: { x: 0, y: thickness + 0.42, z: ey } },
  ];

  ctx.save();
  ctx.fillStyle = "rgba(238,242,255,0.92)";
  ctx.font = '12px Inter, "SF Pro Text", sans-serif';
  points.forEach(({ label, point }) => {
    const p = project(point, scene);
    ctx.fillText(label, p.x + 6, p.y - 4);
  });
  ctx.restore();
}

function tintHex(hex, offset) {
  const rgb = hex.replace("#", "");
  const value = Number.parseInt(rgb, 16);
  const r = clamp(((value >> 16) & 255) + 255 * offset, 0, 255);
  const g = clamp(((value >> 8) & 255) + 255 * offset, 0, 255);
  const b = clamp((value & 255) + 255 * offset, 0, 255);
  return `rgb(${r}, ${g}, ${b})`;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}
