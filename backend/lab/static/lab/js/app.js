function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    return decodeURIComponent(parts.pop().split(';').shift());
  }
  return '';
}

function showToast(message, variant = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${variant}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('visible');
  }, 10);

  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, 2800);
}

function setLoading(button, isLoading, loadingLabel = 'Loading...') {
  if (!button) return;
  if (isLoading) {
    button.dataset.originalText = button.textContent;
    button.disabled = true;
    button.innerHTML = `<span class="spinner small"></span> ${loadingLabel}`;
  } else {
    button.disabled = false;
    button.innerHTML = button.dataset.originalText || button.textContent;
  }
}

async function apiFetch(url, options = {}) {
  const csrfToken = getCookie('csrftoken');
  const defaultHeaders = {
    'Content-Type': 'application/json',
    'X-CSRFToken': csrfToken,
  };

  const response = await fetch(url, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
    credentials: 'same-origin',
  });

  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || 'Request failed.');
  }

  return payload;
}
