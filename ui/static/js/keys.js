// keys.js — Key management panel state machine
//
// States:
//   empty    — no keys loaded
//   partial  — one of two keys uploaded
//   mismatch — both uploaded but keys don't pair
//   unresolvable — public key Pokemon can't be found in DB
//   valid    — both uploaded and validated (or generated)

const TYPES = [
    'normal', 'fire', 'water', 'grass', 'electric', 'ice', 'fighting',
    'poison', 'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost',
    'dragon', 'dark', 'steel', 'fairy'
];
const GENS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

// ---------------------------------------------------------------------------
// setStatus — defined here so app.js can use it too (loads after this file)
// ---------------------------------------------------------------------------

function setStatus(msg, type = '') {
    const el = document.getElementById('status-text');
    if (!el) return;
    el.textContent = msg;
    el.className = type;
}

// ---------------------------------------------------------------------------
// Dropdowns
// ---------------------------------------------------------------------------

function initDropdowns() {
    ['p', 'q'].forEach(slot => {
        const typeEl = document.getElementById(`type-${slot}`);
        const genEl = document.getElementById(`gen-${slot}`);
        TYPES.forEach(t => {
            const o = document.createElement('option');
            o.value = t;
            o.textContent = t.charAt(0).toUpperCase() + t.slice(1);
            typeEl.appendChild(o);
        });
        GENS.forEach(g => {
            const o = document.createElement('option');
            o.value = g;
            o.textContent = `Gen ${g}`;
            genEl.appendChild(o);
        });
    });
    onFilterChange();
}

// ---------------------------------------------------------------------------
// Filter counts and generate button guard
// ---------------------------------------------------------------------------

let _countP = 0;
let _countQ = 0;

async function onFilterChange() {
    await Promise.all([updateCount('p'), updateCount('q')]);
    updateGenerateButton();
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
        if (slot === 'p') _countP = data.matched;
        else _countQ = data.matched;
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

function filtersAreIdentical() {
    return (
        document.getElementById('type-p').value === document.getElementById('type-q').value &&
        document.getElementById('gen-p').value === document.getElementById('gen-q').value
    );
}

function updateGenerateButton() {
    const btn = document.getElementById('generate-btn');
    const hintEl = document.getElementById('generate-hint');
    if (!btn) return;

    let disabled = false;
    let hint = '';

    if (_countP === 0) {
        disabled = true;
        hint = 'Filter P has no matching Pokémon.';
    } else if (_countQ === 0) {
        disabled = true;
        hint = 'Filter Q has no matching Pokémon.';
    } else if (filtersAreIdentical() && _countP < 2) {
        disabled = true;
        hint = 'Identical filters need at least 2 Pokémon to pick from.';
    }

    btn.disabled = disabled;
    if (hint) {
        hintEl.textContent = hint;
        hintEl.classList.remove('hidden');
    } else {
        hintEl.classList.add('hidden');
    }
}

function buildBundle(slot) {
    const type = document.getElementById(`type-${slot}`)?.value;
    const gen = document.getElementById(`gen-${slot}`)?.value;
    const b = {};
    if (type) b.type_primary = type;
    if (gen) b.generation = parseInt(gen);
    return Object.keys(b).length ? b : null;
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

// STATE: empty
function applyStateEmpty() {
    setIndicator('no-keys', 'No keys loaded');
    hide('key-info');
    hide('key-message');
    hide('purge-btn');
    hide('key-divider');
    show('generate-section');
    show('upload-section');
    setSlot('private', false);
    setSlot('public', false);
    enablePanels(false);
    setStatus('Load or generate keys to begin.');
}

// STATE: partial
function applyStatePartial(hasPrivate, hasPublic) {
    setIndicator('partial', 'Partial keys');
    hide('key-info');
    show('key-message');
    const msg = hasPrivate
        ? 'private.key loaded · please provide public.json to continue'
        : 'public.json loaded · please provide private.key to continue';
    setMessage(msg, '');
    show('purge-btn');
    hide('key-divider');
    show('upload-section');
    hide('generate-section');
    setSlot('private', hasPrivate);
    setSlot('public', hasPublic);
    enablePanels(false);
}

// STATE: mismatch
function applyStateMismatch(errorMsg) {
    setIndicator('partial', 'Key mismatch');
    hide('key-info');
    show('key-message');
    setMessage(errorMsg || 'Key mismatch — these keys don\'t work together. Purge and re-upload both files.', 'error');
    show('purge-btn');
    hide('key-divider');
    hide('upload-section');
    hide('generate-section');
    setSlot('private', true);
    setSlot('public', true);
    enablePanels(false);
    setStatus('Key mismatch — purge and re-upload.', 'error');
}

// STATE: unresolvable
function applyStateUnresolvable(errorMsg) {
    setIndicator('partial', 'Unresolvable key');
    hide('key-info');
    show('key-message');
    setMessage(errorMsg, 'warning');
    show('purge-btn');
    hide('key-divider');
    hide('upload-section');
    hide('generate-section');
    setSlot('private', true);
    setSlot('public', true);
    enablePanels(false);
    setStatus('Public key cannot be validated with current database.', 'error');
}

// STATE: valid
function applyStateValid(data) {
    setIndicator('has-keys', 'Keys loaded');
    show('key-info');
    hide('key-message');
    if (data.pokemon_p) {
        document.getElementById('pokemon-p').textContent = data.pokemon_p;
        document.getElementById('pokemon-q').textContent = data.pokemon_q;
        document.getElementById('modulus-bits').textContent = `${data.modulus_bits} bits`;
    }
    show('purge-btn');
    show('key-divider');
    hide('upload-section');
    hide('generate-section');
    setSlot('private', true);
    setSlot('public', true);
    enablePanels(true);
}

// ---------------------------------------------------------------------------
// State helpers
// ---------------------------------------------------------------------------

function setIndicator(cls, text) {
    const dot = document.getElementById('key-indicator');
    if (dot) dot.className = `key-status-indicator ${cls}`;
    const txt = document.getElementById('key-status-text');
    if (txt) txt.textContent = text;
}

function setMessage(text, type) {
    const el = document.getElementById('key-message');
    if (!el) return;
    el.textContent = text;
    el.className = `key-message${type ? ' ' + type : ''}`;
}

function setSlot(which, loaded) {
    const dot = document.getElementById(`slot-dot-${which}`);
    const status = document.getElementById(`slot-status-${which}`);
    const slot = document.getElementById(`slot-${which}`);
    if (!dot || !status || !slot) return;
    dot.className = `slot-dot ${loaded ? 'loaded' : 'empty'}`;
    status.textContent = loaded ? 'loaded' : '— not loaded —';
    if (loaded) slot.classList.add('filled');
    else slot.classList.remove('filled');
}

function show(id) { document.getElementById(id)?.classList.remove('hidden'); }
function hide(id) { document.getElementById(id)?.classList.add('hidden'); }

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
// Generate new keypair
// ---------------------------------------------------------------------------

async function generateKeys() {
    const btn = document.getElementById('generate-btn');
    btn.disabled = true;
    btn.textContent = 'Generating…';
    setStatus('Generating keypair — this may take a moment…', 'working');

    try {
        const resp = await fetch('/api/session/keygen', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bundle_p: buildBundle('p'), bundle_q: buildBundle('q') }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            setStatus(data.error, 'error');
        } else {
            applyStateValid(data);
            setStatus(
                `Keypair ready: ${data.pokemon_p.split(' ')[1]} × ${data.pokemon_q.split(' ')[1]}`,
                'success'
            );
        }
    } catch (err) {
        setStatus(`Network error: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate Keypair';
    }
}

// ---------------------------------------------------------------------------
// Upload individual key file
// ---------------------------------------------------------------------------

async function handleUpload(which, input) {
    const file = input.files[0];
    if (!file) return;

    const formKey = which === 'private' ? 'private_key' : 'public_key';
    const form = new FormData();
    form.append(formKey, file);

    setSlot(which, false); // reset while uploading
    setStatus('Uploading…', 'working');

    try {
        const resp = await fetch('/api/session/keys', { method: 'POST', body: form });
        const data = await resp.json();

        if (!resp.ok) {
            // Surface specific error in status bar
            setStatus(data.error, 'error');
            // Reset file input so user can try again
            input.value = '';
            return;
        }

        // Update slot display immediately
        if (data.saved === 'private_key') setSlot('private', true);
        if (data.saved === 'public_key') setSlot('public', true);

        if (data.state === 'partial') {
            applyStatePartial(data.has_private, data.has_public);
            setStatus(`${which === 'private' ? 'private.key' : 'public.json'} uploaded.`);
        } else if (data.state === 'both') {
            // Both slots filled — trigger validation
            setStatus('Validating key pair…', 'working');
            await validateKeys();
        }
    } catch (err) {
        setStatus(`Upload error: ${err.message}`, 'error');
        input.value = '';
    }
}

// ---------------------------------------------------------------------------
// Validate both keys
// ---------------------------------------------------------------------------

async function validateKeys() {
    try {
        const resp = await fetch('/api/session/validate', { method: 'POST' });
        const data = await resp.json();

        if (data.status === 'valid') {
            applyStateValid(data);
            setStatus(
                `Keys validated: ${data.pokemon_p.split(' ')[1]} × ${data.pokemon_q.split(' ')[1]}`,
                'success'
            );
        } else if (data.status === 'mismatch') {
            applyStateMismatch(data.error);
        } else if (data.status === 'unresolvable') {
            applyStateUnresolvable(data.error);
        } else {
            setStatus(data.error || 'Validation failed.', 'error');
        }
    } catch (err) {
        setStatus(`Validation error: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Purge
// ---------------------------------------------------------------------------

async function purgeKeys() {
    if (!confirm('Delete session keys? This cannot be undone.')) return;
    try {
        await fetch('/api/session/keys', { method: 'DELETE' });
        applyStateEmpty();
        // Reset file inputs so the browser doesn't remember the old selection
        document.getElementById('upload-private').value = '';
        document.getElementById('upload-public').value = '';
    } catch (err) {
        setStatus(`Purge error: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Refresh on load
// ---------------------------------------------------------------------------

async function refreshKeyStatus() {
    try {
        const resp = await fetch('/api/session/status');
        const data = await resp.json();

        if (data.state === 'empty') {
            applyStateEmpty();
        } else if (data.state === 'partial') {
            applyStatePartial(data.has_private, data.has_public);
        } else if (data.state === 'both') {
            await validateKeys();
        }
    } catch (err) {
        console.error('refreshKeyStatus error:', err);
    }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    initDropdowns();
    refreshKeyStatus();
});