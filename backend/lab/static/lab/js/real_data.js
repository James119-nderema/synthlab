const realDataFile = document.getElementById('realDataFile');
const uploadRealDataBtn = document.getElementById('uploadRealDataBtn');
const realDataUploadStatus = document.getElementById('realDataUploadStatus');

uploadRealDataBtn.addEventListener('click', async () => {
  const file = realDataFile.files[0];
  if (!file) {
    showToast('Choose an academic CSV file first.', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);
  uploadRealDataBtn.disabled = true;
  realDataUploadStatus.textContent = 'Uploading and profiling…';
  try {
    const response = await fetch('/api/upload/', {
      method: 'POST',
      body: formData,
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error(payload.error || 'Upload failed.');
    realDataUploadStatus.textContent = `Uploaded ${file.name}. Continue to preprocessing.`;
    showToast('Real academic data uploaded.', 'success');
  } catch (error) {
    realDataUploadStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    uploadRealDataBtn.disabled = false;
  }
});
