// app.js — Main UI logic, live encrypt/decrypt with debounce
// NOTE: setStatus is defined in keys.js which loads before this file.

const DEBOUNCE_MS = 800;

let debounceTimer    = null;
let lastActivePanel  = null;
let currentEncrypted = null;

// ---------------------------------------------------------------------------
// Panel input handlers
// ---------------------------------------------------------------------------

function onPanelInput(panel) {
  if (!window.keysReady) return;

  clearTimeout(debounceTimer);

  const plain  = document.getElementById('textarea-plain');
  const cipher = document.getElementById('textarea-cipher');

  if (panel === 'plain') {
    lastActivePanel = 'plain';
    cipher.value = '';
    clearExportButtons();
    setDirection('encrypt');
    if (!plain.value.trim()) { setStatus(''); return; }
  } else {
    lastActivePanel = 'cipher';
    plain.value = '';
    clearExportButtons();
    setDirection('decrypt');
    if (!cipher.value.trim()) { setStatus(''); return; }
  }

  setStatus('Waiting…', 'working');

  debounceTimer = setTimeout(() => {
    if (panel === 'plain') {
      doEncrypt(plain.value);
    } else {
      doDecrypt(cipher.value);
    }
  }, DEBOUNCE_MS);
}

// ---------------------------------------------------------------------------
// Direction indicator
// ---------------------------------------------------------------------------

function setDirection(dir) {
  const arrow       = document.getElementById('divider-arrow');
  const label       = document.getElementById('direction-label');
  const panelPlain  = document.getElementById('panel-plain');
  const panelCipher = document.getElementById('panel-cipher');

  if (dir === 'encrypt') {
    arrow.textContent = '→';
    arrow.className   = 'divider-arrow encrypt';
    label.textContent = '— encrypting →';
    panelPlain.classList.add('active');
    panelCipher.classList.remove('active');
  } else if (dir === 'decrypt') {
    arrow.textContent = '←';
    arrow.className   = 'divider-arrow decrypt';
    label.textContent = '← decrypting —';
    panelCipher.classList.add('active');
    panelPlain.classList.remove('active');
  } else {
    arrow.textContent = '⟷';
    arrow.className   = 'divider-arrow';
    label.textContent = window.keysReady
      ? '— type in either panel —'
      : '— awaiting keys —';
    panelPlain.classList.remove('active');
    panelCipher.classList.remove('active');
  }
}

// ---------------------------------------------------------------------------
// Encrypt
// ---------------------------------------------------------------------------

async function doEncrypt(message) {
  if (!message.trim()) return;
  setStatus('Encrypting…', 'working');

  try {
    const resp = await fetch('/api/encrypt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    });
    const data = await resp.json();

    if (!resp.ok) {
      setStatus(`Encryption error: ${data.error}`, 'error');
      return;
    }

    document.getElementById('textarea-cipher').value = data.encrypted_inline;
    currentEncrypted = data.encrypted_raw;  // raw JSON string preserves large int precision

    document.getElementById('hint-plain').textContent  =
      `${message.length} chars · ${data.blocks} block${data.blocks !== 1 ? 's' : ''}`;
    document.getElementById('hint-cipher').textContent =
      `${data.blocks} RSA block${data.blocks !== 1 ? 's' : ''}`;

    document.getElementById('export-cipher').classList.remove('hidden');
    setStatus('Encrypted successfully.', 'success');

  } catch (err) {
    console.error('doEncrypt error:', err);
    setStatus(`Error: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Decrypt
// ---------------------------------------------------------------------------

async function doDecrypt(encryptedRaw) {
  if (!encryptedRaw.trim()) return;
  setStatus('Decrypting…', 'working');

  // Validate it's parseable JSON before sending, but don't use the parsed value —
  // sending the raw string preserves large integer precision (JS floats lose it)
  try { JSON.parse(encryptedRaw); } catch {
    setStatus('Invalid JSON in ciphertext panel.', 'error');
    return;
  }

  try {
    const resp = await fetch('/api/decrypt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ encrypted_raw: encryptedRaw }),
    });
    const data = await resp.json();

    if (!resp.ok) {
      setStatus(`Decryption error: ${data.error}`, 'error');
      return;
    }

    document.getElementById('textarea-plain').value = data.plaintext;
    document.getElementById('hint-plain').textContent  = `${data.plaintext.length} chars`;
    document.getElementById('hint-cipher').textContent = 'decrypted ✓';
    document.getElementById('export-plain').classList.remove('hidden');
    setStatus('Decrypted successfully.', 'success');

  } catch (err) {
    console.error('doDecrypt error:', err);
    setStatus(`Error: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

function exportFile(type) {
  if (type === 'plain') {
    const text = document.getElementById('textarea-plain').value;
    if (!text) return;
    download('plaintext.txt', text, 'text/plain');
  } else {
    if (!currentEncrypted) return;
    download('encrypted.json', currentEncrypted, 'application/json');
  }
}

function download(filename, content, mime) {
  const a    = document.createElement('a');
  const blob = new Blob([content], { type: mime });
  a.href     = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function clearExportButtons() {
  document.getElementById('export-plain').classList.add('hidden');
  document.getElementById('export-cipher').classList.add('hidden');
  document.getElementById('hint-plain').textContent  = '';
  document.getElementById('hint-cipher').textContent = '';
  currentEncrypted = null;
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  setDirection(null);
});