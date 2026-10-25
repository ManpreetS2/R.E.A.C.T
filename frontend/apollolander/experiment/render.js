"use strict";

// Canvas drawing shared by the live page (index.html) and the replay page (replay.html).
(function () {
  function project(x, y, camera) {
    return [
      (x - camera.left) / camera.width * camera.screenWidth,
      (y - camera.top) / camera.height * camera.screenHeight,
    ];
  }

  function stroke(context, points, camera) {
    context.beginPath();
    points.forEach((point, index) => {
      const [sx, sy] = project(point.x, point.y, camera);
      if (index === 0) context.moveTo(sx, sy);
      else context.lineTo(sx, sy);
    });
    context.stroke();
  }

  // map: sim.mapInfo(); frame: sim.frameGeometry()
  function drawScene(context, map, frame) {
    const camera = frame.camera;
    context.fillStyle = "#000006";
    context.fillRect(0, 0, 1920, 1080);
    context.save();
    context.strokeStyle = "#F0F6FF";
    context.lineWidth = 1.5;
    stroke(context, map.points, camera);
    context.strokeStyle = "#d6de7a";
    context.lineWidth = 4;
    const [x1, y1] = project(frame.zone.x1, frame.zone.y, camera);
    const [x2] = project(frame.zone.x2, frame.zone.y, camera);
    context.beginPath();
    context.moveTo(x1, y1);
    context.lineTo(x2, y1);
    context.stroke();
    context.strokeStyle = "#F0F6FF";
    context.lineWidth = 1.6;
    for (const line of frame.lander) stroke(context, line, camera);
    if (frame.thrust) stroke(context, frame.thrust, camera);
    context.restore();
  }

  const renderApi = { drawScene, project };
  if (typeof window !== "undefined") window.ApolloRender = renderApi;
  if (typeof module !== "undefined" && module.exports) module.exports = renderApi;
})();
