/* Owner gallery ordering. Saved images have an id; pending images are uploaded on save. */

(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.AutonoventGalleryOrder = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const maxImages = 4;

  function moveLeft(items, index) {
    const next = items.slice();
    if (!Number.isInteger(index) || index < 1 || index >= next.length) {
      return next;
    }
    const moved = next[index];
    next[index] = next[index - 1];
    next[index - 1] = moved;
    return next;
  }

  function without(items, index) {
    return items.filter((_item, position) => position !== index);
  }

  function room(items) {
    return Math.max(0, maxImages - items.length);
  }

  function savedIds(items) {
    return items.filter((item) => item.kind === "saved").map((item) => item.id);
  }

  function serverOrder(items, uploadedIds) {
    let next = 0;
    return items.map((item) => (item.kind === "saved" ? item.id : uploadedIds[next++])).filter(Boolean);
  }

  return {
    maxImages: maxImages,
    moveLeft: moveLeft,
    without: without,
    room: room,
    savedIds: savedIds,
    serverOrder: serverOrder,
  };
});
