// keys.js — Key management panel logic
// NOTE: setStatus is defined here since keys.js loads first and app.js depends on it too.

const TYPES = [
    'normal', 'fire', 'water', 'grass', 'electric', 'ice', 'fighting',
    'poison', 'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost',
    'dragon', 'dark', 'steel', 'fairy'
];

const GENS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

// ---------------------------------------------------------------------------
// Status bar — defined here so both keys.js and app.js can use it
// ---------------------------------------------------------------------------

function setStatus(msg, type = '') {
    const el = document.getElementById('status-text');
    if (!el) return;
    el.textContent = msg;
    el.className = type;
}

// ---------------------------------------------------------------------------
// Initialise dropdowns
// ---------------------------------------------------------------------------

function initDropdowns() {
    ['p', 'q'].forEach(slot => {
        const typeEl = document.getElementById(`type-${slot}`);
        const genEl = document.getElementById(`gen-${slot}`);

        TYPES.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t.charAt(0).toUpperCase() + t.slice(1);
            typeEl.appendChild(opt);
        });

        GENS.forEach(g => {
            const opt = document.createElement('option');
            opt.value = g;
            opt.textContent = `Gen ${g}`;
            genEl.appendChild(opt);
        });
    });

    updateCount('p');
    updateCount('q');
}

// ---------------------------------------------------------------------------
// Bundle building from filter dropdowns
// ---------------------------------------------------------------------------

function buildBundle(slot) {
    const typeEl = document.getElementById(`type-${slot}`);
    const genEl = document.getElementById(`gen-${slot}`);

    if (!typeEl || !genEl) {
        console.error(`Could not find filter elements for slot: ${slot}`);
        return null;
    }

    const type = typeEl.value;
    const gen = genEl.value;
    const bundle = {};
    if (type) bundle.type_primary = type;
    if (gen) bundle.generation = parseInt(gen);
    return Object.keys(bundle).length ? bundle : null;
}

async function updateCount(slot) {
    const bundle = buildBundle(slot);
    const countEl = document.getElementById(`count-${slot}`);
    if (!countEl) return;
    countEl.textContent = '…';

    try {
        const resp = await fetch('/api/bundle/count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bundle }),
        });
        if (!resp.ok) { countEl.textContent = 'err'; return; }
        const data = await resp.json();
        countEl.textContent = `${data.matched} / ${data.total}`;
        countEl.style.color = data.matched === 0
            ? 'var(--red)'
            : data.matched === 1
                ? 'var(--yellow)'
                : 'var(--green)';
    } catch (err) {
        console.error('updateCount error:', err);
        countEl.textContent = '—';
    }
}

// ---------------------------------------------------------------------------
// Generate new keypair
// ---------------------------------------------------------------------------

async function generateKeys() {
    const btn = document.getElementById('generate-btn');
    btn.disabled = true;
    btn.textContent = 'Generating…';
    setStatus('Generating keypair — this may take a moment…', 'working');

    const bundle_p = buildBundle('p');
    const bundle_q = buildBundle('q');
    console.log('Generating keys with:', { bundle_p, bundle_q });

    try {
        const resp = await fetch('/api/session/keygen', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bundle_p, bundle_q }),
        });
        console.log('keygen response status:', resp.status);
        const data = await resp.json();
        console.log('keygen response data:', data);

        if (!resp.ok) {
            setStatus(`Key generation failed: ${data.error}`, 'error');
        } else {
            onKeysLoaded(data);
            setStatus(
                `Keypair ready: ${data.pokemon_p.split(' ')[1]} × ${data.pokemon_q.split(' ')[1]}`,
                'success'
            );
        }
    } catch (err) {
        console.error('generateKeys fetch error:', err);
        setStatus(`Network error: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Keypair';
    }
}

// ---------------------------------------------------------------------------
// Upload existing keys
// ---------------------------------------------------------------------------

async function uploadKeys() {
    const privateFile = document.getElementById('upload-private').files[0];
    const publicFile = document.getElementById('upload-public').files[0];
    if (!privateFile && !publicFile) return;

    const form = new FormData();
    if (privateFile) form.append('private_key', privateFile);
    if (publicFile) form.append('public_key', publicFile);

    setStatus('Uploading keys…', 'working');
    try {
        const resp = await fetch('/api/session/keys', { method: 'POST', body: form });
        const data = await resp.json();
        if (!resp.ok) {
            setStatus(`Upload failed: ${data.error}`, 'error');
        } else {
            await refreshKeyStatus();
            setStatus('Keys uploaded successfully.', 'success');
        }
    } catch (err) {
        console.error('uploadKeys error:', err);
        setStatus(`Error: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Purge keys
// ---------------------------------------------------------------------------

async function purgeKeys() {
    if (!confirm('Delete session keys? This cannot be undone.')) return;
    try {
        await fetch('/api/session/keys', { method: 'DELETE' });
        onKeysCleared();
        setStatus('Session keys purged.', '');
    } catch (err) {
        setStatus(`Error: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Key state UI helpers
// ---------------------------------------------------------------------------

function onKeysLoaded(data) {
    document.getElementById('key-indicator').className = 'key-status-indicator has-keys';
    document.getElementById('key-status-text').textContent = 'Keys loaded';

    if (data.pokemon_p) {
        document.getElementById('key-info').classList.remove('hidden');
        document.getElementById('pokemon-p').textContent = data.pokemon_p;
        document.getElementById('pokemon-q').textContent = data.pokemon_q;
        document.getElementById('modulus-bits').textContent = `${data.modulus_bits} bits`;
    }

    // Show purge button directly under key info; hide generate/upload sections
    document.getElementById('purge-btn').classList.remove('hidden');
    document.getElementById('key-divider').classList.remove('hidden');
    document.getElementById('key-actions').classList.add('hidden');
    enablePanels(true);
}

function onKeysCleared() {
    document.getElementById('key-indicator').className = 'key-status-indicator no-keys';
    document.getElementById('key-status-text').textContent = 'No keys loaded';
    document.getElementById('key-info').classList.add('hidden');

    // Hide purge button; restore generate/upload sections
    document.getElementById('purge-btn').classList.add('hidden');
    document.getElementById('key-divider').classList.add('hidden');
    document.getElementById('key-actions').classList.remove('hidden');
    enablePanels(false);
}

async function refreshKeyStatus() {
    try {
        const resp = await fetch('/api/session/status');
        const data = await resp.json();
        if (data.keys_loaded) {
            onKeysLoaded({});
        } else {
            onKeysCleared();
        }
    } catch (err) {
        console.error('refreshKeyStatus error:', err);
    }
}

window.keysReady = false;

function enablePanels(enabled) {
    window.keysReady = enabled;
    document.getElementById('textarea-plain').disabled = !enabled;
    document.getElementById('textarea-cipher').disabled = !enabled;
    document.getElementById('direction-label').textContent = enabled
        ? '— type in either panel —'
        : '— awaiting keys —';
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    initDropdowns();
    refreshKeyStatus();
});