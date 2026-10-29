(() => {
  const editor = document.getElementById("editor");
  const form = document.getElementById("article-form");
  const hidden = document.getElementById("body_html");
  const imageInput = document.getElementById("image-input");
  const imageButton = document.getElementById("image-button");
  const status = document.getElementById("editor-status");
  if (!editor || !form || !hidden) return;

  const coverInput = document.getElementById("cover_url");
  const coverFile = document.getElementById("cover-input");
  const coverButton = document.getElementById("cover-button");
  const coverClear = document.getElementById("cover-clear");
  const coverPreview = document.getElementById("cover-preview");
  const coverPreviewWrap = document.getElementById("cover-preview-wrap");
  const mediaDialog = document.getElementById("media-dialog");
  const mediaGrid = document.getElementById("media-grid");
  const mediaClose = document.getElementById("media-close");

  const sync = () => { hidden.value = editor.innerHTML; };
  const announce = (text) => {
    if (!status) return;
    status.textContent = text;
    window.setTimeout(() => { status.textContent = ""; }, 3000);
  };

  const insertImage = (url, alt) => {
    const figure = document.createElement("figure");
    figure.className = "align-center";
    const img = document.createElement("img");
    img.src = url;
    img.alt = alt || "Imagen";
    figure.appendChild(img);
    editor.focus();
    document.execCommand("insertHTML", false, figure.outerHTML);
    sync();
    scheduleDraft();
  };

  const uploadImage = async (file) => {
    const data = new FormData();
    data.append("image", file);
    const response = await fetch("/admin/upload", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Error al subir");
    return payload;
  };

  const showCover = (url) => {
    if (!coverPreview || !coverPreviewWrap) return;
    coverPreview.src = url || "";
    coverPreviewWrap.hidden = !url;
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
      announce("Subiendo imagen…");
      try {
        const payload = await uploadImage(file);
        insertImage(payload.url, file.name.replace(/\.[^.]+$/, ""));
        announce("Imagen insertada");
      } catch (error) {
        announce(error.message || "No se pudo subir la imagen");
      }
    });
  }

  const urlButton = document.getElementById("image-url-button");
  if (urlButton) {
    urlButton.addEventListener("click", () => {
      const url = window.prompt("URL de la imagen (https://… o /media/…)", "https://");
      if (!url) return;
      if (!url.startsWith("/media/") && !url.startsWith("https://") && !url.startsWith("http://")) {
        announce("Usa una URL http(s) o /media/");
        return;
      }
      insertImage(url, "Imagen");
      sync();
    });
  }

  if (coverButton && coverFile && coverInput) {
    coverButton.addEventListener("click", () => coverFile.click());
    coverFile.addEventListener("change", async () => {
      const file = coverFile.files && coverFile.files[0];
      coverFile.value = "";
      if (!file) return;
      announce("Subiendo portada…");
      try {
        const payload = await uploadImage(file);
        coverInput.value = payload.url;
        showCover(payload.url);
        scheduleDraft();
        announce("Portada subida");
      } catch (error) {
        announce(error.message || "No se pudo subir la portada");
      }
    });
    coverInput.addEventListener("input", () => showCover(coverInput.value.trim()));
  }
  if (coverClear && coverInput) {
    coverClear.addEventListener("click", () => {
      coverInput.value = "";
      showCover("");
    });
  }

  const closeMedia = () => {
    if (mediaDialog && mediaDialog.open) mediaDialog.close();
  };
  if (mediaClose) mediaClose.addEventListener("click", closeMedia);

  const openLibrary = async () => {
    if (!mediaDialog || !mediaGrid) return;
    mediaGrid.innerHTML = '<p class="hint">Cargando…</p>';
    mediaDialog.showModal();
    try {
      const response = await fetch("/admin/media", { headers: { Accept: "application/json" } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "No se pudo cargar");
      if (!payload.items || payload.items.length === 0) {
        mediaGrid.innerHTML = '<p class="hint">Todavía no has subido imágenes.</p>';
        return;
      }
      mediaGrid.innerHTML = "";
      payload.items.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "media-item";
        button.title = item.name || "Imagen";
        const img = document.createElement("img");
        img.src = item.url;
        img.alt = item.name || "Imagen";
        img.loading = "lazy";
        button.appendChild(img);
        button.addEventListener("click", () => {
          insertImage(item.url, item.name || "Imagen");
          closeMedia();
        });
        mediaGrid.appendChild(button);
      });
    } catch (error) {
      mediaGrid.innerHTML = `<p class="hint">${error.message || "No se pudo cargar la biblioteca"}</p>`;
    }
  };
  const libraryButton = document.getElementById("library-button");
  if (libraryButton) libraryButton.addEventListener("click", openLibrary);

  editor.addEventListener("paste", async (event) => {
    const items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    const files = Array.from(items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length === 0) return;
    event.preventDefault();
    for (const file of files) {
      announce("Subiendo imagen pegada…");
      try {
        const payload = await uploadImage(file);
        insertImage(payload.url, file.name || "Imagen pegada");
      } catch (error) {
        announce(error.message || "No se pudo subir la imagen pegada");
      }
    }
  });

  const draftKey = form.dataset.draftKey;
  const updatedEpoch = Number(form.dataset.updatedEpoch || 0);
  const storageKey = draftKey ? `osap.blog.draft.${draftKey}` : "";
  const titleInput = document.getElementById("title");
  const summaryInput = document.getElementById("summary");
  let draftTimer = 0;

  const collectDraft = () => ({
    ts: Math.floor(Date.now() / 1000),
    title: titleInput ? titleInput.value : "",
    summary: summaryInput ? summaryInput.value : "",
    cover_url: coverInput ? coverInput.value : "",
    body: editor.innerHTML,
  });

  const saveDraft = () => {
    if (!storageKey) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify(collectDraft()));
      announce("Borrador local guardado");
    } catch {
      // localStorage puede estar deshabilitado; no interrumpir la edición.
    }
  };

  const scheduleDraft = () => {
    window.clearTimeout(draftTimer);
    draftTimer = window.setTimeout(saveDraft, 800);
  };

  const restoreDraft = () => {
    if (!storageKey) return;
    let draft = null;
    try {
      const raw = localStorage.getItem(storageKey);
      draft = raw ? JSON.parse(raw) : null;
    } catch {
      draft = null;
    }
    if (!draft || !draft.ts || draft.ts <= updatedEpoch + 5) return;
    const when = new Date(draft.ts * 1000).toLocaleString();
    if (!window.confirm(`Hay un borrador local de ${when}. ¿Restaurarlo?`)) {
      localStorage.removeItem(storageKey);
      return;
    }
    if (titleInput) titleInput.value = draft.title || "";
    if (summaryInput) summaryInput.value = draft.summary || "";
    if (coverInput) coverInput.value = draft.cover_url || "";
    editor.innerHTML = draft.body || "";
    showCover(draft.cover_url || "");
    sync();
    announce("Borrador local restaurado");
  };

  [titleInput, summaryInput, coverInput].forEach((field) => {
    if (field) field.addEventListener("input", scheduleDraft);
  });
  editor.addEventListener("input", scheduleDraft);
  form.addEventListener("submit", () => {
    sync();
    saveDraft();
  });
  window.setTimeout(restoreDraft, 100);
})();
