// Per-team challenge form (create and update): shows only the fields for the chosen mode, reads
// chosen files into the form (they are sent with Create/Update and checked on the server before
// anything is saved), shows the sample flag, and edits variants.
(() => {
  const root = document.querySelector(".cl-form");
  if (!root) return;
  const form = root.closest("form");
  const delivery = root.querySelector("#cl-delivery");
  const template = root.querySelector("#cl-template");
  const sample = root.querySelector("#cl-sample");
  const MAX_BYTES = 100 * 1024 * 1024;
  let reading = 0;

  function submitButtons(disabled) {
    form.querySelectorAll("button[type=submit], input[type=submit]").forEach(b => (b.disabled = disabled));
  }

  // Sections ----------------------------------------------------------------------------------
  function showMode() {
    const mode = delivery.value;
    root.querySelectorAll("[data-cl-show]").forEach(section => {
      section.style.display = section.dataset.clShow.split(" ").includes(mode) ? "" : "none";
    });
  }
  delivery.addEventListener("change", () => { showMode(); showSample(); });

  // Sample flag -------------------------------------------------------------------------------
  function showSample() {
    const value = template.value.trim();
    const count = (value.match(/\{team\}/g) || []).length;
    sample.classList.remove("text-danger", "text-muted");
    if (!value) {
      sample.textContent = "";
    } else if (count !== 1) {
      sample.classList.add("text-danger");
      sample.textContent = "Use {team} exactly once.";
    } else {
      const flag = value.replace("{team}", "X".repeat(12));
      sample.classList.add("text-muted");
      sample.textContent = delivery.value === "replace"
        ? `Sample flag to put in your file: ${flag} (${flag.length} characters)`
        : `A team's flag looks like: ${value.replace("{team}", "93e2e0400f5c")}`;
    }
  }
  template.addEventListener("input", showSample);

  // Files -------------------------------------------------------------------------------------
  root.querySelectorAll("[data-cl-upload]").forEach(input => {
    const field = root.querySelector(`input[type=hidden][name="${input.dataset.clUpload}"]`);
    const status = root.querySelector(`[data-cl-status="${input.dataset.clUpload}"]`);
    input.addEventListener("change", () => {
      field.value = "";
      status.className = "form-text";
      const file = input.files[0];
      if (!file) { status.textContent = ""; return; }
      if (file.size > MAX_BYTES) {
        input.value = "";
        status.className = "form-text text-danger";
        status.textContent = `${file.name} is larger than 100 MB.`;
        return;
      }
      reading += 1;
      submitButtons(true);
      status.className = "form-text text-muted";
      status.textContent = `Reading ${file.name}…`;
      const reader = new FileReader();
      reader.onload = () => {
        const data = String(reader.result).split(",", 2)[1] || "";
        field.value = JSON.stringify({ name: file.name, data });
        status.className = "form-text text-success";
        status.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB) will be checked and saved when you press ${form.querySelector("button[type=submit]")?.textContent.trim() || "save"}.`;
      };
      reader.onerror = () => {
        input.value = "";
        status.className = "form-text text-danger";
        status.textContent = `${file.name} could not be read. Choose it again.`;
      };
      reader.onloadend = () => {
        reading -= 1;
        if (!reading) submitButtons(false);
      };
      reader.readAsDataURL(file);
    });
  });

  // Variants ----------------------------------------------------------------------------------
  const variantList = root.querySelector("#cl-variants");
  const variantField = root.querySelector("#cl-variants-json");
  let variants = [];
  try { variants = JSON.parse(variantField.value || "[]"); } catch (e) { variants = []; }
  if (!Array.isArray(variants)) variants = [];
  while (variants.length < 2) variants.push({ description: "", answer: "" });

  function syncVariants() {
    variantField.value = JSON.stringify(variants.filter(v => v.answer.trim() || v.description.trim()));
  }

  function renderVariants() {
    variantList.replaceChildren();
    variants.forEach((variant, index) => {
      const row = document.createElement("div");
      row.className = "form-row mb-2";
      row.innerHTML = `
        <div class="col-md-7"><textarea class="form-control" rows="2" placeholder="Variant ${index + 1} task (markdown)"></textarea></div>
        <div class="col-md-4"><input class="form-control" placeholder="Answer"></div>
        <div class="col-md-1"><button type="button" class="btn btn-outline-danger btn-sm" title="Remove">✕</button></div>`;
      const [text, answer, remove] = [row.querySelector("textarea"), row.querySelector("input"), row.querySelector("button")];
      text.value = variant.description || "";
      answer.value = variant.answer || "";
      text.addEventListener("input", () => { variant.description = text.value; syncVariants(); });
      answer.addEventListener("input", () => { variant.answer = answer.value; syncVariants(); });
      remove.addEventListener("click", () => { variants.splice(index, 1); renderVariants(); });
      variantList.appendChild(row);
    });
    syncVariants();
  }
  root.querySelector("#cl-add-variant").addEventListener("click", () => {
    variants.push({ description: "", answer: "" });
    renderVariants();
  });
  // Variant rows have no name attribute, so only the hidden JSON field is sent.
  renderVariants();

  showMode();
  showSample();
})();
