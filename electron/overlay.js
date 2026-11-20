(function installCpmhOverlay() {
  function pageSize() {
    var root = document.documentElement;
    var body = document.body;
    return {
      width: Math.max(root.scrollWidth, body ? body.scrollWidth : 0, root.clientWidth),
      height: Math.max(root.scrollHeight, body ? body.scrollHeight : 0, root.clientHeight),
    };
  }

  function apply(payload) {
    window.__cpmhOverlay = payload || { regions: [], visible: true };
    var size = pageSize();
    var layer = document.getElementById("cpmh-overlay");
    if (!layer) {
      layer = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      layer.setAttribute("id", "cpmh-overlay");
      layer.style.position = "absolute";
      layer.style.left = "0";
      layer.style.top = "0";
      layer.style.pointerEvents = "none";
      layer.style.zIndex = "2147483646";
      (document.body || document.documentElement).appendChild(layer);
    }
    layer.setAttribute("width", String(size.width));
    layer.setAttribute("height", String(size.height));
    layer.style.width = size.width + "px";
    layer.style.height = size.height + "px";
    layer.style.display = payload && payload.visible === false ? "none" : "block";
    var categories = {};
    ((payload && payload.categories) || []).forEach(function (item) {
      categories[item] = true;
    });
    var filtering = Object.keys(categories).length > 0;
    var markup = ((payload && payload.regions) || []).filter(function (region) {
      return !filtering || categories[region.category];
    }).map(function (region) {
      var box = region.bbox || [0, 0, 0, 0];
      var x = box[0] * size.width;
      var y = box[1] * size.height;
      var width = box[2] * size.width;
      var height = box[3] * size.height;
      var selected = payload.selectedId && payload.selectedId === region.id;
      var id = String(region.id || "").replace(/[^A-Za-z0-9_-]/g, "");
      return '<rect data-region="' + id + '" x="' + x + '" y="' + y + '" width="' + width + '" height="' + height + '" fill="none" stroke="' + (selected ? "#ff5000" : "#29282A") + '" stroke-width="2"></rect>';
    }).join("");
    layer.innerHTML = markup;
  }

  window.cpmhApplyOverlay = apply;
  if (!window.__cpmhOverlayBound) {
    window.__cpmhOverlayBound = true;
    window.addEventListener("resize", function () {
      if (window.__cpmhOverlay) apply(window.__cpmhOverlay);
    });
  }
})();
