(() => {
  const editor = document.getElementById("editor");
  const form = document.getElementById("article-form");
  const hidden = document.getElementById("body_html");
  const imageInput = document.getElementById("image-input");
  const imageButton = document.getElementById("image-button");
  const status = document.getElementById("editor-status");
  if (!editor || !form || !hidden) return;

  const sync = () => { hidden.value = editor.innerHTML; };
  const announce = (text) => {
    if (!status) return;
    status.textContent = text;
    window.setTimeout(() => { status.textContent = ""; }, 2500);
  };

  form.addEventListener("submit", sync);
  editor.addEventListener("input", sync);
  sync();

  document.querySelectorAll(".toolbar [data-cmd]").forEach((button) => {
    button.addEventListener("click", () => {
      editor.focus();
      const command = button.dataset.cmd;
      if (command === "createLink") {
        const href = window.prompt("URL del enlace", "https://");
        if (href) document.execCommand("createLink", false, href);
      } else if (command === "formatBlock") {
        document.execCommand("formatBlock", false, button.dataset.value || "p");
      } else {
        document.execCommand(command, false);
      }
      sync();
    });
  });

  const alignImage = (className) => {
    editor.focus();
    const selection = window.getSelection();
    let node = selection && selection.anchorNode;
    while (node && node !== editor && !(node instanceof HTMLImageElement) && !(node instanceof HTMLElement && node.tagName === "FIGURE")) {
      node = node.parentNode;
    }
    if (!node || node === editor) {
      announce("Selecciona una imagen");
      return;
    }
    let figure = node instanceof HTMLImageElement ? node.closest("figure") : node;
    if (!figure || figure.tagName !== "FIGURE") {
      const image = node instanceof HTMLImageElement ? node : node.querySelector("img");
      if (!image) { announce("Selecciona una imagen"); return; }
      figure = document.createElement("figure");
      image.replaceWith(figure);
      figure.appendChild(image);
    }
    figure.classList.remove("align-left", "align-right", "align-center", "media-wide");
    figure.classList.add(className);
    sync();
  };

  document.querySelectorAll("[data-align]").forEach((button) => {
    button.addEventListener("click", () => alignImage(button.dataset.align));
  });

  if (imageButton && imageInput) {
    imageButton.addEventListener("click", () => imageInput.click());
    imageInput.addEventListener("change", async () => {
      const file = imageInput.files && imageInput.files[0];
      imageInput.value = "";
      if (!file) return;
      const data = new FormData();
      data.append("image", file);
      announce("Subiendo imagen…");
      try {
        const response = await fetch("/admin/upload", { method: "POST", body: data });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Error al subir");
        const figure = document.createElement("figure");
        figure.className = "align-center";
        const img = document.createElement("img");
        img.src = payload.url;
        img.alt = file.name.replace(/\.[^.]+$/, "");
        figure.appendChild(img);
        editor.focus();
        document.execCommand("insertHTML", false, figure.outerHTML);
        sync();
        announce("Imagen insertada");
      } catch (error) {
        announce(error.message || "No se pudo subir la imagen");
      }
    });
  }
})();
