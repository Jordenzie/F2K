const STATUS_COLORS = {
  PASS: "#59E8DF",
  PASS_WITH_WARNINGS: "#8CEEDB",
  WARNING: "#8CEEDB",
  OUTSIDE_SCOPE: "#7AD0FF",
  WAITING: "#4D726A",
};

export class FootingViewer {
  constructor(container) {
    this.container = container;
    this.canvas = document.createElement("canvas");
    this.overlay = document.createElement("div");
    this.overlay.className = "viewer-overlay";
    this.overlay.innerHTML = "<span>Drag to orbit</span><span>Shift + drag to pan</span>";
    this.container.append(this.canvas, this.overlay);

    this.context = this.canvas.getContext("2d");
    this.rotationX = -0.58;
    this.rotationY = 0.72;
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
        this.rotationY = startRotY + deltaX * 0.008;
        this.rotationX = clamp(startRotX + deltaY * 0.006, -1.25, 0.1);
      }

      this.render();
    });

    this.canvas.addEventListener("pointerup", (event) => {
      dragging = false;
      this.canvas.releasePointerCapture(event.pointerId);
    });

    this.canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.rotationY += event.deltaY * 0.0009;
      this.render();
    });
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

    const sceneScale = Math.min(width / (footingLength + 5), height / (footingWidth + thickness + 6)) * 20;
    const scene = {
      cx: width * 0.5 + this.panX,
      cy: height * 0.64 + this.panY,
      scale: clamp(sceneScale, 22, 54),
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

    footingFaces.forEach((face, index) => {
      drawables.push({
        depth: averageDepth(face, scene),
        draw: () =>
          drawFace(
            ctx,
            face,
            scene,
            tintHex(footingColor, index === 0 ? 0.08 : index === 1 ? -0.04 : -0.12),
            "#8BECE2"
          ),
      });
    });

    columnFaces.forEach((face, index) => {
      drawables.push({
        depth: averageDepth(face, scene),
        draw: () =>
          drawFace(
            ctx,
            face,
            scene,
            index === 0 ? "#D8FFF1" : index === 1 ? "#A4E7DE" : "#7DB8C9",
            "#D8FFF1"
          ),
      });
    });

    drawables.sort((a, b) => a.depth - b.depth).forEach((item) => item.draw());

    drawPolyline(ctx, [...kernPoints, kernPoints[0]], scene, "#7AD0FF", 2.2, [6, 5]);
    drawPolyline(ctx, [centroidPoint, loadPoint], scene, "#9DE7D1", 2, [5, 5]);
    drawMarker(ctx, centroidPoint, scene, "#59E8DF", 4.5);
    drawMarker(ctx, loadPoint, scene, "#D8FFF1", 5.5);
    drawLoadArrow(ctx, loadPoint, scene);
    drawPressureBars(ctx, footingLength, footingWidth, thickness, qmin, qmax, scene);
    drawLabels(ctx, footingLength, footingWidth, thickness, eccentricityX, eccentricityY, scene);
  }
}

function drawBackground(ctx, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#17302C");
  gradient.addColorStop(1, "#0A1413");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255,255,255,0.04)";
  ctx.lineWidth = 1;
  for (let x = 0; x < width; x += 32) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(183,247,217,0.07)";
  ctx.beginPath();
  ctx.ellipse(width * 0.52, height * 0.16, width * 0.34, height * 0.18, 0, 0, Math.PI * 2);
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
    [p.ltf, p.rtf, p.rtb, p.ltb],
    [p.lbb, p.rbb, p.rtb, p.ltb],
    [p.rbf, p.rbb, p.rtb, p.rtf],
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
  ctx.strokeStyle = "#9DE7D1";
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
  ctx.fillStyle = "#9DE7D1";
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
      index < 3 ? "rgba(89,232,223,0.38)" : "rgba(183,247,217,0.28)",
      "rgba(216,255,241,0.32)"
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
  ctx.fillStyle = "rgba(237,246,241,0.88)";
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
