(() => {
  "use strict";

  const API = "/api/v1";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const storage = {
    token: "vocalis.accessToken",
    guest: "vocalis.guestId",
  };

  function getToken() {
    return localStorage.getItem(storage.token);
  }

  function guestId() {
    let value = localStorage.getItem(storage.guest);
    if (!value) {
      value = crypto.randomUUID();
      localStorage.setItem(storage.guest, value);
    }
    return value;
  }

  function headers(extra = {}) {
    const result = { ...extra };
    const token = getToken();
    if (token) result.Authorization = `Bearer ${token}`;
    return result;
  }

  async function api(path, options = {}) {
    const requestHeaders = headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData)) {
      requestHeaders["Content-Type"] = "application/json";
    }
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: requestHeaders,
    });
    if (response.status === 401 && getToken()) {
      localStorage.removeItem(storage.token);
      if (["dashboard", "billing", "playground"].includes(window.VOCALIS_PAGE)) {
        window.location.assign(`/login?next=${encodeURIComponent(location.pathname)}`);
      }
    }
    if (!response.ok) {
      let message = `Request failed (${response.status}).`;
      try {
        const data = await response.json();
        message = typeof data.detail === "string" ? data.detail : message;
      } catch {
        // Keep the HTTP status as the actionable fallback for non-JSON responses.
      }
      throw new Error(message);
    }
    if (response.status === 204) return null;
    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("application/json") ? response.json() : response;
  }

  function toast(message, kind = "") {
    const region = $("[data-toast]");
    if (!region) return;
    const item = document.createElement("div");
    item.className = `toast ${kind}`.trim();
    item.textContent = message;
    region.append(item);
    window.setTimeout(() => item.remove(), 4600);
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? "—"
      : new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", year: "numeric" }).format(date);
  }

  function money(amount) {
    return new Intl.NumberFormat("en-KE", {
      style: "currency",
      currency: "KES",
      maximumFractionDigits: 0,
    }).format(Number(amount));
  }

  function setAuthNavigation() {
    const token = getToken();
    const authNav = $("[data-auth-nav]");
    const userNav = $("[data-user-nav]");
    if (authNav && userNav) {
      authNav.hidden = Boolean(token);
      userNav.hidden = !token;
    }
    $$("[data-logout]").forEach((button) => button.addEventListener("click", () => {
      localStorage.removeItem(storage.token);
      window.location.assign("/");
    }));
    if (["dashboard", "billing", "playground"].includes(window.VOCALIS_PAGE) && !token) {
      window.location.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
    }
  }

  function setupNavigation() {
    const toggle = $("[data-menu-toggle]");
    const menu = $("[data-menu]");
    if (!toggle || !menu) return;
    toggle.addEventListener("click", () => {
      const open = menu.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    });
    menu.addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        menu.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  function setupStudio() {
    const form = $("[data-studio-form]");
    if (!form) return;
    let step = 1;
    const steps = $$("[data-step]", form);
    const indicators = $$("[data-step-indicator]");

    function showStep(next) {
      step = next;
      steps.forEach((element) => element.classList.toggle("active", Number(element.dataset.step) === step));
      indicators.forEach((element) => {
        const number = Number(element.dataset.stepIndicator);
        element.classList.toggle("active", number === step);
        element.classList.toggle("complete", number < step);
      });
      form.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function validateCurrentStep() {
      const current = steps.find((element) => Number(element.dataset.step) === step);
      const controls = $$("input, textarea, select", current);
      const invalid = controls.find((control) => !control.checkValidity());
      if (invalid) {
        invalid.reportValidity();
        return false;
      }
      return true;
    }

    $$("[data-next]").forEach((button) => button.addEventListener("click", () => {
      if (!validateCurrentStep()) return;
      if (step === 2) {
        const data = new FormData(form);
        $("[data-review-title]").textContent = data.get("title");
        $("[data-review-traits]").textContent = `${data.get("gender")} · ${data.get("age_range")} · ${data.get("ethnicity")}`;
      }
      showStep(Math.min(3, step + 1));
    }));
    $$("[data-back]").forEach((button) => button.addEventListener("click", () => showStep(Math.max(1, step - 1))));

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (step !== 3 || !validateAll()) return;
      const submit = $("[data-generate]", form);
      const result = $("[data-studio-result]");
      const originalLabel = submit.innerHTML;
      submit.disabled = true;
      submit.textContent = "Creating your voice…";
      result.hidden = true;
      try {
        const values = new FormData(form);
        const payload = Object.fromEntries(["title", "gender", "age_range", "ethnicity", "description"].map((key) => [key, values.get(key)]));
        const response = await api("/voices/generate", {
          method: "POST",
          headers: getToken() ? {} : { "X-Guest-ID": guestId() },
          body: JSON.stringify(payload),
        });
        renderGeneratedVoice(result, response);
        result.hidden = false;
        result.scrollIntoView({ behavior: "smooth", block: "center" });
        toast("Your new voice is ready.", "success");
        if (!getToken()) localStorage.setItem("vocalis.guestVoiceId", response.id);
      } catch (error) {
        if (error.message.includes("Guest generation has already been used") && !getToken()) {
          toast("You've reached your free trial limit. <a href='/register'>Create an account</a> to continue.", "error");
        } else {
          toast(error.message, "error");
        }
      } finally {
        submit.disabled = false;
        submit.innerHTML = originalLabel;
      }
    });

    function validateAll() {
      const invalid = $$("input, textarea, select", form).find((control) => !control.checkValidity());
      if (!invalid) return true;
      const parent = invalid.closest("[data-step]");
      if (parent) showStep(Number(parent.dataset.step));
      invalid.reportValidity();
      return false;
    }
  }

  function safeAudioUrl(value) {
    if (!value) return null;
    try {
      const url = new URL(value, location.origin);
      return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }

  function renderGeneratedVoice(container, voice) {
    container.replaceChildren();
    const title = document.createElement("h2");
    title.textContent = `${voice.title} is ready.`;
    const description = document.createElement("p");
    description.textContent = `${voice.gender} · ${voice.age_range} · ${voice.ethnicity}`;
    const actions = document.createElement("div");
    actions.className = "result-actions";
    const library = document.createElement("a");
    library.className = "button button-outline";
    library.href = getToken() ? "/voices" : "/register";
    library.textContent = getToken() ? "Open your library →" : "Create an account to save it →";
    actions.append(library);
    const playground = document.createElement("a");
    playground.className = "button button-primary";
    playground.href = getToken() ? `/playground?voice=${encodeURIComponent(voice.id)}` : "/register";
    playground.textContent = getToken() ? "Try it in the playground →" : "Sign up to download";
    actions.append(playground);
    container.append(title, description);
    const audioUrl = safeAudioUrl(voice.preview_url);
    if (audioUrl) {
      const audio = document.createElement("audio");
      audio.className = "audio-inline";
      audio.controls = true;
      audio.preload = "none";
      audio.src = audioUrl;
      container.append(audio);
      if (getToken()) {
        const download = document.createElement("a");
        download.className = "button button-outline";
        download.href = `/api/v1/voices/${encodeURIComponent(voice.id)}/download`;
        download.textContent = "Download voice";
        actions.append(download);
      }
    }
    container.append(actions);
  }

  let currentLibraryTab = "voices";
  let loadedVoices = [];
  let loadedAlbums = [];
  let loadedDrafts = [];

  function setupLibrary() {
    const grid = $("[data-voice-grid]");
    if (!grid) return;
    const search = $("[data-voice-search]");
    grid.addEventListener("click", (event) => {
      if (!(event.target instanceof Element)) return;
      const button = event.target.closest("[data-voice-action]");
      if (button) onVoiceAction(button);
    });
    $$("[data-library-tab]").forEach((button) => button.addEventListener("click", () => {
      currentLibraryTab = button.dataset.libraryTab;
      $$("[data-library-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
      if (search) search.hidden = currentLibraryTab === "albums" || currentLibraryTab === "drafts";
      const create = $("[data-album-toolbar]");
      if (create) create.hidden = currentLibraryTab !== "albums" || !getToken();
      renderLibrary();
    }));
    search?.addEventListener("input", renderLibrary);
    $("[data-create-album]")?.addEventListener("click", createAlbum);
    loadLibrary();

    async function loadLibrary() {
      try {
        const listHeaders = getToken() ? {} : { "X-Guest-ID": guestId() };
        loadedVoices = await api("/voices", { headers: listHeaders });
        if (getToken()) {
          loadedAlbums = await api("/albums");
          loadedDrafts = await api("/voices?status=failed");
        }
        const count = $("[data-voice-count]");
        if (count) count.textContent = String(loadedVoices.length);
        renderLibrary();
      } catch (error) {
        grid.innerHTML = `<div class="loading-card">${escapeHtml(error.message)}${!getToken() ? ' <a href="/login">Sign in</a>' : ""}</div>`;
      }
    }

    function renderLibrary() {
      const empty = $("[data-library-empty]");
      if (currentLibraryTab === "albums") {
        if (!getToken()) {
          grid.innerHTML = '<div class="loading-card">Sign in to create and organize albums. <a href="/login">Sign in →</a></div>';
          if (empty) empty.hidden = true;
          return;
        }
        grid.innerHTML = loadedAlbums.length ? loadedAlbums.map(renderAlbumCard).join("") : '<div class="loading-card">No albums yet. Create one to organize voices by project.</div>';
        grid.querySelectorAll("[data-delete-album]").forEach((button) => button.addEventListener("click", () => deleteAlbum(button.dataset.deleteAlbum)));
        grid.querySelectorAll("[data-edit-album]").forEach((button) => button.addEventListener("click", () => editAlbum(button.dataset.editAlbum)));
        grid.querySelectorAll("[data-add-album-voice]").forEach((button) => button.addEventListener("click", () => addVoiceToAlbum(button.dataset.addAlbumVoice)));
        if (empty) empty.hidden = true;
        return;
      }
      if (currentLibraryTab === "drafts") {
        if (!getToken()) {
          grid.innerHTML = '<div class="loading-card">Sign in to view your drafts. <a href="/login">Sign in →</a></div>';
          if (empty) empty.hidden = true;
          return;
        }
        grid.innerHTML = loadedDrafts.length ? loadedDrafts.map(renderVoiceCard).join("") : '<div class="loading-card">No failed voice generations. All your voices are working perfectly.</div>';
        if (empty) empty.hidden = true;
        return;
      }
      const query = search?.value.trim().toLowerCase() || "";
      const filtered = loadedVoices.filter((voice) => `${voice.title} ${voice.description} ${voice.ethnicity}`.toLowerCase().includes(query));
      grid.innerHTML = filtered.map(renderVoiceCard).join("");
      if (empty) empty.hidden = loadedVoices.length > 0;
      if (!loadedVoices.length) grid.innerHTML = "";
    }

    function renderVoiceCard(voice) {
      const metadata = [voice.gender, voice.age_range, voice.ethnicity].filter(Boolean).map(escapeHtml).join(" · ");
      const audioUrl = safeAudioUrl(voice.preview_url);
      const playable = audioUrl ? `<a href="${escapeHtml(audioUrl)}" target="_blank" rel="noopener">Listen</a>` : "";
      const actions = getToken()
        ? `<button type="button" data-voice-action="edit" data-id="${escapeHtml(voice.id)}">Edit</button><button type="button" data-voice-action="regenerate" data-id="${escapeHtml(voice.id)}">Regenerate</button><a href="/playground?voice=${encodeURIComponent(voice.id)}">Playground</a>${playable}<a href="/api/v1/voices/${encodeURIComponent(voice.id)}/download">Download</a><button type="button" class="button button-danger" data-voice-action="delete" data-id="${escapeHtml(voice.id)}">Delete</button>`
        : `${playable}<a href="/register">Sign in to save</a>`;
      return `<article class="voice-card"><div class="voice-card-top"><div class="voice-avatar">${escapeHtml((voice.title || "V").slice(0, 1).toUpperCase())}</div><div class="voice-card-title"><b>${escapeHtml(voice.title)}</b><span>${metadata}</span></div></div><p class="voice-card-description">${escapeHtml(voice.description)}</p><div class="voice-card-actions">${actions}</div></article>`;
    }

    function renderAlbumCard(album) {
      const actions = getToken()
        ? `<button type="button" data-edit-album="${escapeHtml(album.id)}">Edit</button><button type="button" data-add-album-voice="${escapeHtml(album.id)}">＋ Add voice</button><button type="button" data-delete-album="${escapeHtml(album.id)}">Delete</button>`
        : "";
      return `<article class="album-card"><div class="album-cover" aria-hidden="true">▤</div><h3>${escapeHtml(album.title)}</h3><p>${escapeHtml(album.description || "A collection of voices for your next idea.")}</p><small>${album.voice_ids.length} ${album.voice_ids.length === 1 ? "voice" : "voices"}</small><div class="voice-card-actions">${actions}</div>${album.voice_ids.length ? `<p>Voice IDs: ${album.voice_ids.map(escapeHtml).join(", ")}</p>` : ""}</article>`;
    }

    async function onVoiceAction(button) {
      const { voiceAction: action, id } = button.dataset;
      const voice = [...loadedVoices, ...loadedDrafts].find((item) => item.id === id);
      if (!voice) return;
      if (action === "delete") {
        if (!window.confirm(`Delete "${voice.title}"? This will delete its voice reference and remove it from all albums. This cannot be undone.`)) return;
        try {
          await api(`/voices/${encodeURIComponent(id)}`, { method: "DELETE" });
          loadedVoices = loadedVoices.filter((item) => item.id !== id);
          loadedDrafts = loadedDrafts.filter((item) => item.id !== id);
          // Reload albums to update voice references
          if (getToken()) {
            loadedAlbums = await api("/albums");
          }
          renderLibrary();
          toast("Voice deleted.", "success");
        } catch (error) { toast(error.message, "error"); }
      } else if (action === "edit") {
        editVoice(voice, false);
      } else if (action === "regenerate") {
        editVoice(voice, true);
      }
    }
  }

  async function createAlbum() {
    if (!getToken()) return window.location.assign("/login");
    const modal = $("[data-voice-modal]");
    const content = $("[data-modal-content]");
    content.innerHTML = `<span class="eyebrow">YOUR VOICE COLLECTION</span><h2>Create an album.</h2><p>Bring together the voices you want to keep close.</p><form data-album-form><label class="field-label" for="album-title">Album name</label><input id="album-title" name="title" maxlength="100" placeholder="e.g. Brand stories" required><label class="field-label" for="album-description">Description</label><textarea id="album-description" name="description" rows="3" maxlength="2000" placeholder="What are you making?"></textarea><button class="button button-primary button-wide" type="submit">Create album →</button></form>`;
    modal.showModal();
    $("[data-album-form]", content).addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      try {
        await api("/albums", {
          method: "POST",
          body: JSON.stringify({ title: data.get("title"), description: data.get("description") }),
        });
        modal.close();
        toast("Album created.", "success");
        $(`[data-library-tab="albums"]`)?.click();
      } catch (error) { toast(error.message, "error"); }
    });
  }

  async function editAlbum(id) {
    const album = loadedAlbums.find((item) => item.id === id);
    if (!album) return;
    const modal = $("[data-voice-modal]");
    const content = $("[data-modal-content]");
    content.innerHTML = `<span class="eyebrow">YOUR VOICE COLLECTION</span><h2>Edit album.</h2><p>Make this collection feel like yours.</p><form data-album-form><label class="field-label" for="album-title">Album name</label><input id="album-title" name="title" maxlength="100" required value="${escapeHtml(album.title)}"><label class="field-label" for="album-description">Description</label><textarea id="album-description" name="description" rows="3" maxlength="2000">${escapeHtml(album.description)}</textarea><button class="button button-primary button-wide" type="submit">Save album →</button></form>`;
    modal.showModal();
    $("[data-album-form]", content).addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      try {
        await api(`/albums/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: JSON.stringify({ title: data.get("title"), description: data.get("description") }),
        });
        modal.close();
        toast("Album updated.", "success");
        $(`[data-library-tab="albums"]`)?.click();
      } catch (error) { toast(error.message, "error"); }
    });
  }

  async function deleteAlbum(id) {
    if (!window.confirm("Delete this album? Your voices will stay in your library.")) return;
    try {
      await api(`/albums/${encodeURIComponent(id)}`, { method: "DELETE" });
      toast("Album deleted.", "success");
      location.reload();
    } catch (error) { toast(error.message, "error"); }
  }

  async function addVoiceToAlbum(albumId) {
    if (!loadedVoices.length) return toast("Create a voice before adding one to an album.", "error");
    const modal = $("[data-voice-modal]");
    const content = $("[data-modal-content]");
    content.innerHTML = `<span class="eyebrow">ALBUM CURATION</span><h2>Add a voice.</h2><p>Choose one of your saved voices for this collection.</p><form data-add-voice-form><label class="field-label" for="album-voice">Your voices</label><select id="album-voice" name="voice_id" required>${loadedVoices.map((voice) => `<option value="${escapeHtml(voice.id)}">${escapeHtml(voice.title)} · ${escapeHtml(voice.ethnicity)}</option>`).join("")}</select><button class="button button-primary button-wide" type="submit">Add to album →</button></form>`;
    modal.showModal();
    $("[data-add-voice-form]", content).addEventListener("submit", async (event) => {
      event.preventDefault();
      const voiceId = new FormData(event.currentTarget).get("voice_id");
      try {
        await api(`/albums/${encodeURIComponent(albumId)}/voices/${encodeURIComponent(voiceId)}`, { method: "POST" });
        modal.close();
        toast("Voice added to album.", "success");
        $(`[data-library-tab="albums"]`)?.click();
      } catch (error) { toast(error.message, "error"); }
    });
  }

  function editVoice(voice, regenerate) {
    const modal = $("[data-voice-modal]");
    const content = $("[data-modal-content]");
    if (!modal || !content) return;
    content.innerHTML = `<span class="eyebrow">${regenerate ? "REGENERATE YOUR VOICE" : "VOICE DETAILS"}</span><h2>${regenerate ? "Change the feeling." : "A few thoughtful edits."}</h2><p>${regenerate ? "Update the description and settings, then create a fresh version." : "Edit the details your voice is built around."}</p><form data-edit-voice><label class="field-label" for="edit-title">Voice name</label><input id="edit-title" name="title" maxlength="100" required value="${escapeHtml(voice.title)}"><label class="field-label" for="edit-gender">Gender</label><input id="edit-gender" name="gender" maxlength="40" required value="${escapeHtml(voice.gender)}"><label class="field-label" for="edit-age">Age range</label><input id="edit-age" name="age_range" maxlength="80" required value="${escapeHtml(voice.age_range)}"><label class="field-label" for="edit-ethnicity">Accent or cultural identity</label><input id="edit-ethnicity" name="ethnicity" maxlength="100" required value="${escapeHtml(voice.ethnicity)}"><label class="field-label" for="edit-description">Voice description</label><textarea id="edit-description" name="description" minlength="20" maxlength="2000" required>${escapeHtml(voice.description)}</textarea><button class="button button-primary button-wide" type="submit">${regenerate ? "Regenerate voice →" : "Save changes →"}</button></form>`;
    modal.showModal();
    $("[data-edit-voice]", content).addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = new FormData(form);
      const all = Object.fromEntries(["title", "gender", "age_range", "ethnicity", "description"].map((key) => [key, data.get(key)]));
      const payload = all;
      try {
        const updated = await api(`/voices/${encodeURIComponent(voice.id)}${regenerate ? "/regenerate" : ""}`, {
          method: regenerate ? "POST" : "PATCH",
          body: JSON.stringify(payload),
        });
        const position = loadedVoices.findIndex((item) => item.id === voice.id);
        if (position >= 0) loadedVoices[position] = updated;
        loadedDrafts = loadedDrafts.filter((item) => item.id !== voice.id);
        modal.close();
        toast(regenerate ? "Voice regenerated." : "Voice updated.", "success");
        $(`[data-library-tab="${currentLibraryTab}"]`)?.click();
      } catch (error) { toast(error.message, "error"); }
    });
  }

  function setupPlayground() {
    const select = $("[data-play-voice]");
    if (!select) return;
    if (!getToken()) return;
    const presetVoice = new URLSearchParams(location.search).get("voice");
    const text = $("[data-play-text]");
    const counter = $("[data-character-count]");
    const rate = $("[data-play-rate]");
    const volume = $("[data-play-volume]");
    const audio = $("[data-audio]");
    const output = $("[data-audio-output]");
    let audioUrl = null;
    text.addEventListener("input", () => { counter.textContent = String(text.value.length); });
    rate.addEventListener("input", () => { $("[data-rate-value]").textContent = `${Number(rate.value).toFixed(1)}×`; });
    volume.addEventListener("input", () => { $("[data-volume-value]").textContent = `${Math.round(Number(volume.value) * 100)}%`; });
    select.addEventListener("change", updateSelectedVoice);
    api("/voices").then((voices) => {
      select.innerHTML = '<option value="">Choose a voice</option>' + voices.map((voice) => `<option value="${escapeHtml(voice.id)}">${escapeHtml(voice.title)} · ${escapeHtml(voice.ethnicity)}</option>`).join("");
      if (presetVoice && voices.some((voice) => voice.id === presetVoice)) select.value = presetVoice;
      updateSelectedVoice();
    }).catch((error) => {
      select.innerHTML = '<option value="">Your voice library is unavailable</option>';
      toast(error.message, "error");
    });

    function updateSelectedVoice() {
      const voice = select.options[select.selectedIndex]?.value;
      const selected = $("[data-selected-voice]");
      const item = select.options[select.selectedIndex];
      selected.querySelector("b").textContent = voice ? item.textContent.split(" · ")[0] : "Select a voice to begin";
      selected.querySelector("span").textContent = voice ? item.textContent.split(" · ").slice(1).join(" · ") : "Your voice details will appear here";
    }

    $("[data-synthesize]").addEventListener("click", async (event) => {
      if (!select.value) return toast("Choose a voice first.", "error");
      if (!text.value.trim()) return toast("Write something for your voice to say.", "error");
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "Finding the right words…";
      try {
        const response = await api("/playground/speech", {
          method: "POST",
          body: JSON.stringify({
            voice_id: select.value,
            text: text.value,
            speaking_rate: Number(rate.value),
            volume: Number(volume.value),
            style: $("[data-play-style]").value || null,
          }),
        });
        const blob = await response.blob();
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        audioUrl = URL.createObjectURL(blob);
        audio.src = audioUrl;
        $("[data-audio-download]").href = audioUrl;
        output.hidden = false;
        audio.play().catch(() => {});
        toast("Your audio is ready.", "success");
      } catch (error) { toast(error.message, "error"); }
      finally {
        button.disabled = false;
        button.innerHTML = "Generate speech <span>→</span>";
      }
    });
  }

  function setupDashboard() {
    const target = $("[data-dashboard-credits]");
    if (!target || !getToken()) return;
    Promise.all([api("/dashboard"), api("/voices")]).then(([dashboard, voices]) => {
      target.textContent = dashboard.credits_balance.toLocaleString("en-KE");
      $("[data-dashboard-voices]").textContent = String(dashboard.voice_count);
      $("[data-dashboard-albums]").textContent = String(dashboard.album_count);
      const recent = $("[data-dashboard-recent]");
      recent.innerHTML = voices.slice(0, 3).map((voice) => `
        <article class="voice-card"><div class="voice-card-top"><div class="voice-avatar">${escapeHtml(voice.title.slice(0, 1).toUpperCase())}</div><div class="voice-card-title"><b>${escapeHtml(voice.title)}</b><span>${escapeHtml(voice.gender)} · ${escapeHtml(voice.ethnicity)}</span></div></div><p class="voice-card-description">${escapeHtml(voice.description)}</p><div class="voice-card-actions"><a href="/playground?voice=${encodeURIComponent(voice.id)}">Try in playground</a></div></article>`).join("") || '<div class="loading-card">Your first voice is just around the corner.</div>';
      const ledger = $("[data-dashboard-ledger]");
      ledger.innerHTML = dashboard.recent_transactions.length
        ? dashboard.recent_transactions.map(renderLedgerRow).join("")
        : '<tr><td colspan="4">Your credit activity will appear here.</td></tr>';
    }).catch((error) => toast(error.message, "error"));
  }

  function renderLedgerRow(item) {
    const delta = Number(item.delta);
    return `<tr><td>${escapeHtml(item.kind.replaceAll("_", " "))}</td><td>${formatDate(item.created_at)}</td><td class="${delta >= 0 ? "positive" : "negative"}">${delta > 0 ? "+" : ""}${delta.toLocaleString("en-KE")}</td><td>${Number(item.balance_after).toLocaleString("en-KE")}</td></tr>`;
  }

  function setupBilling() {
    const packGrid = $("[data-pack-grid]");
    if (!packGrid) return;
    let selectedPack = null;
    const modal = $("[data-payment-modal]");
    const content = $("[data-payment-content]");
    loadPacks();
    if (getToken()) loadBillingData();

    async function loadPacks() {
      try {
        const packs = await api("/credit-packs");
        packGrid.innerHTML = packs.map((pack, index) => `
          <article class="pack-card ${index === 1 ? "featured" : ""}">${index === 1 ? '<span class="pack-featured-tag">MOST POPULAR</span>' : ""}<span class="pack-label">${escapeHtml(pack.title.toUpperCase())} PACK</span><h3>${escapeHtml(pack.title)}</h3><span class="pack-credits">${Number(pack.credits).toLocaleString("en-KE")} credits</span><div class="pack-price">${money(pack.amount_kes)} <small>one time</small></div><button class="button ${index === 1 ? "button-primary" : "button-outline"}" type="button" data-buy-pack="${escapeHtml(pack.id)}">Choose pack <span>→</span></button></article>`).join("");
        packGrid.querySelectorAll("[data-buy-pack]").forEach((button) => button.addEventListener("click", () => {
          selectedPack = packs.find((pack) => pack.id === button.dataset.buyPack);
          showPaymentOptions();
        }));
      } catch (error) {
        packGrid.innerHTML = `<div class="loading-card">${escapeHtml(error.message)}</div>`;
      }
    }

    async function loadBillingData() {
      try {
        const [balance, payments] = await Promise.all([api("/credits"), api("/payments")]);
        const balanceEl = $("[data-billing-balance]");
        if (balanceEl) balanceEl.innerHTML = `${Number(balance.balance).toLocaleString("en-KE")} <small>credits</small>`;
        const history = $("[data-payment-history]");
        if (history) history.innerHTML = payments.length ? payments.map((payment) => `<tr><td>${formatDate(payment.created_at)}</td><td>${escapeHtml(payment.method.replaceAll("_", " "))} · ${money(payment.amount_kes)}</td><td>${Number(payment.credits).toLocaleString("en-KE")}</td><td><span class="status-pill status-${escapeHtml(payment.status)}">${escapeHtml(payment.status)}</span></td></tr>`).join("") : '<tr><td colspan="4">No payments yet. Your first pack is waiting.</td></tr>';
      } catch (error) { toast(error.message, "error"); }
    }

    function showPaymentOptions() {
      content.innerHTML = `<span class="eyebrow">YOUR NEXT CREATIVE SPARK</span><h2>${escapeHtml(selectedPack.title)} pack</h2><p>${Number(selectedPack.credits).toLocaleString("en-KE")} credits · ${money(selectedPack.amount_kes)} KES</p><form data-payment-form><span class="field-label">Choose how to pay</span><div class="payment-options"><label class="payment-option"><input name="payment-method" type="radio" value="stk" checked> M-Pesa STK push</label><label class="payment-option"><input name="payment-method" type="radio" value="paybill"> Paybill</label><label class="payment-option"><input name="payment-method" type="radio" value="till"> M-Pesa Till</label><label class="payment-option"><input name="payment-method" type="radio" value="qr"> Scan QR</label><label class="payment-option"><input name="payment-method" type="radio" value="card"> Card</label></div><div data-phone-field><label class="field-label" for="payment-phone">M-Pesa phone number</label><input id="payment-phone" name="phone_number" type="tel" inputmode="tel" placeholder="0712 345 678" pattern="(\\+?254|0)?[17][0-9]{8}" required></div><button class="button button-primary button-wide" type="submit" data-checkout-button>Continue securely <span>→</span></button></form><div class="payment-result" data-payment-result hidden></div>`;
      modal.showModal();
      const form = $("[data-payment-form]", content);
      const phoneField = $("[data-phone-field]", content);
      $$('input[name="payment-method"]', form).forEach((radio) => radio.addEventListener("change", () => {
        phoneField.hidden = radio.value !== "stk" || !radio.checked;
      }));
      form.addEventListener("submit", startCheckout);
    }

    async function startCheckout(event) {
      event.preventDefault();
      const form = event.currentTarget;
      const method = new FormData(form).get("payment-method");
      const button = $("[data-checkout-button]", form);
      button.disabled = true;
      button.textContent = "Connecting securely…";
      const result = $("[data-payment-result]", content);
      try {
        let response;
        if (method === "stk") {
          response = await api("/payments/mpesa/stk", {
            method: "POST",
            body: JSON.stringify({ pack_id: selectedPack.id, phone_number: new FormData(form).get("phone_number") }),
          });
        } else if (method === "card") {
          response = await api("/payments/card", { method: "POST", body: JSON.stringify({ pack_id: selectedPack.id }) });
          if (response.checkout_url) return window.location.assign(response.checkout_url);
        } else {
          response = await api(`/payments/mpesa/manual?method=${encodeURIComponent(method)}`, {
            method: "POST",
            body: JSON.stringify({ pack_id: selectedPack.id }),
          });
        }
        await showPaymentResult(response, result);
      } catch (error) {
        toast(error.message, "error");
        result.hidden = false;
        result.textContent = error.message;
      } finally {
        button.disabled = false;
        button.innerHTML = "Continue securely <span>→</span>";
      }
    }

    async function showPaymentResult(payment, result) {
      const info = payment.instructions || {};
      if (payment.qr_code_base64) {
        const prefix = payment.qr_code_base64.startsWith("data:") ? "" : "data:image/png;base64,";
        result.innerHTML = `<strong>Scan to pay ${money(payment.amount_kes)}</strong><img alt="M-Pesa payment QR code" src="${prefix}${escapeHtml(payment.qr_code_base64)}"><p>Use your M-Pesa app to scan. Reference: <b>${escapeHtml(payment.account_reference)}</b></p>`;
      } else if (info.paybill || info.till) {
        result.innerHTML = `<strong>Pay ${money(payment.amount_kes)} by M-Pesa ${info.paybill ? "Paybill" : "Till"}</strong><p>${info.paybill ? `Paybill: <b>${escapeHtml(info.paybill)}</b><br>` : `Till: <b>${escapeHtml(info.till)}</b><br>`}Account/reference: <b>${escapeHtml(info.account_reference)}</b><br>Amount: <b>${escapeHtml(info.amount_kes)} KES</b></p><p>We’ll add credits after payment confirmation.</p>`;
      } else {
        result.textContent = "M-Pesa payment request sent. Approve the STK push on your phone. We’ll update your credits when payment is confirmed.";
      }
      result.hidden = false;
      if (payment.id && payment.status === "pending") pollPayment(payment.id, result);
    }

    async function pollPayment(id, result) {
      for (let attempt = 0; attempt < 30 && modal.open; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
        try {
          const payment = await api(`/payments/${encodeURIComponent(id)}`);
          if (payment.status === "paid") {
            result.textContent = "Payment confirmed — your credits are ready.";
            toast("Credits added to your account.", "success");
            loadBillingData();
            return;
          }
          if (payment.status === "failed") {
            result.textContent = "This payment did not go through. You can try another method.";
            return;
          }
        } catch (error) { toast(error.message, "error"); return; }
      }
    }
  }

  function setupAuth() {
    const form = $("[data-auth-form]");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      
      const button = $("[data-auth-submit]", form);
      const email = form.elements.email.value.trim();
      const password = form.elements.password.value;
      
      console.log("Auth form submitted:", { email, password, authMode: form.dataset.authMode });
      
      if (!email || !password) {
        toast("Please fill in all fields.", "error");
        return;
      }
      
      const endpoint = form.dataset.authMode === "register" ? "/auth/register" : "/auth/login";
      button.disabled = true;
      button.textContent = form.dataset.authMode === "register" ? "Creating your account…" : "Signing you in…";
      
      try {
        console.log("Calling API:", endpoint);
        const response = await api(endpoint, {
          method: "POST",
          headers: endpoint.endsWith("register") ? { "X-Guest-ID": guestId() } : {},
          body: JSON.stringify({ email, password }),
        });
        console.log("API response:", response);
        localStorage.setItem(storage.token, response.access_token);
        localStorage.removeItem(storage.guestVoiceId);
        toast("Welcome to Vocalis.", "success");
        const destination = new URLSearchParams(location.search).get("next");
        window.location.assign(destination?.startsWith("/") ? destination : "/dashboard");
      } catch (error) {
        console.error("Auth error:", error);
        toast(error.message, "error");
      } finally {
        button.disabled = false;
        button.innerHTML = `${form.dataset.authMode === "register" ? "Create your account" : "Sign in"} <span>→</span>`;
      }
    });
  }

  function setupGoogleSignIn() {
    const button = $("[data-google-signin]");
    if (!button) return;
    button.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const config = window.VOCALIS_FIREBASE || {};
      if (!config.apiKey || !config.authDomain || !config.projectId || !config.appId) {
        return toast("Google sign-in is not configured yet. Use email and password instead.", "error");
      }
      button.disabled = true;
      try {
        const appSdk = await import("https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js");
        const authSdk = await import("https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js");
        const firebaseApp = appSdk.initializeApp(config, "vocalis-web-auth");
        const auth = authSdk.getAuth(firebaseApp);
        const result = await authSdk.signInWithPopup(auth, new authSdk.GoogleAuthProvider());
        const idToken = await result.user.getIdToken();
        const response = await api("/auth/firebase", {
          method: "POST",
          body: JSON.stringify({ id_token: idToken }),
        });
        localStorage.setItem(storage.token, response.access_token);
        window.location.assign("/dashboard");
      } catch (error) {
        toast(error.message || "Google sign-in could not be completed.", "error");
      } finally {
        button.disabled = false;
      }
    });
  }

  function setupDemoPlay() {
    const button = $("[data-demo-play]");
    if (!button) return;
    button.addEventListener("click", () => {
      toast("Create a voice in the studio to hear your own sample.");
      window.location.assign("/studio");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupNavigation();
    setAuthNavigation();
    setupStudio();
    setupLibrary();
    setupPlayground();
    setupDashboard();
    setupBilling();
    setupAuth();
    setupGoogleSignIn();
    setupDemoPlay();
  });
})();
