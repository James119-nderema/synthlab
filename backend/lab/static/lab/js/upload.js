const uploadZone = document.getElementById('uploadZone');
const uploadInput = document.getElementById('uploadInput');
const selectFileBtn = document.getElementById('selectFileBtn');
const clearFileBtn = document.getElementById('clearFileBtn');
const fileMeta = document.getElementById('fileMeta');

function updateMeta(file) {
  if (!file) {
    fileMeta.innerHTML = '<span class="meta-label">No file selected</span>';
    return;
  }

  fileMeta.innerHTML = `
    <span class="meta-label">Selected file</span>
    <strong>${file.name}</strong>
    <span>${(file.size / 1024 / 1024).toFixed(2)} MB</span>
  `;
}

selectFileBtn.addEventListener('click', () => uploadInput.click());
clearFileBtn.addEventListener('click', () => {
  uploadInput.value = '';
  updateMeta(null);
});

uploadInput.addEventListener('change', (event) => {
  const file = event.target.files[0];
  updateMeta(file);
});

uploadZone.addEventListener('click', () => uploadInput.click());
uploadZone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    uploadInput.click();
  }
});

['dragenter', 'dragover'].forEach((eventName) => {
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.add('dragover');
  });
});

['dragleave', 'drop'].forEach((eventName) => {
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.remove('dragover');
  });
});

uploadZone.addEventListener('drop', (event) => {
  const file = event.dataTransfer.files[0];
  if (file) {
    uploadInput.files = event.dataTransfer.files;
    updateMeta(file);
  }
});
