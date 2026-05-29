// keys.js — Key management panel: state machine + filter/search/keygen

// ---------------------------------------------------------------------------
// setStatus — defined here so app.js (loads after) can use it too
// ---------------------------------------------------------------------------

function setStatus(msg, type = '') {
    const el = document.getElementById('status-text');
    if (!el) return;
    el.textContent = msg;
    el.className = type;
}

// ---------------------------------------------------------------------------
// Field configuration for dynamic filter rows
// ---------------------------------------------------------------------------

const FIELD_CONFIG = {
    type_primary: {
        label: 'Primary type', input: 'select',
        options: ['normal', 'fire', 'water', 'grass', 'electric', 'ice', 'fighting',
            'poison', 'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost',
            'dragon', 'dark', 'steel', 'fairy'],
    },
    type_secondary: {
        label: 'Secondary type', input: 'select',
        options: ['__null__', 'normal', 'fire', 'water', 'grass', 'electric', 'ice',
            'fighting', 'poison', 'ground', 'flying', 'psychic', 'bug', 'rock',
            'ghost', 'dragon', 'dark', 'steel', 'fairy'],
        optionLabels: { '__null__': '(none / single type)' },
    },
    generation: {
        label: 'Generation', input: 'select',
        options: [1, 2, 3, 4, 5, 6, 7, 8, 9],
        formatOption: g => `Gen ${g}`,
    },
    color: {
        label: 'Color', input: 'select',
        options: ['black', 'blue', 'brown', 'gray', 'green', 'pink', 'purple', 'red', 'white', 'yellow'],
    },
    form: {
        label: 'Form', input: 'select',
        options: ['default', 'alola', 'galar', 'hisui', 'paldea'],
    },
    base_stat_total: {
        label: 'BST', input: 'integer',
        attrs: { type: 'text', placeholder: 'e.g. 525', inputmode: 'numeric' },
    },
    height: {
        label: 'Height (m)', input: 'decimal',
        attrs: { type: 'text', placeholder: 'e.g. 1.7', inputmode: 'decimal' },
    },
    weight: {
        label: 'Weight (kg)', input: 'decimal',
        attrs: { type: 'text', placeholder: 'e.g. 90.5', inputmode: 'decimal' },
    },
};

// ---------------------------------------------------------------------------
// Per-slot state
// ---------------------------------------------------------------------------

const slotState = {
    p: { rows: [], locked: null, _count: 0, _total: 0 },
    q: { rows: [], locked: null, _count: 0, _total: 0 },
};

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function capitalize(s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : '';
}

function escapeHtml(s) {
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function uid() {
    return Math.random().toString(36).slice(2, 8);
}

// ---------------------------------------------------------------------------
// Bundle construction
// ---------------------------------------------------------------------------

function buildBundle(slot) {
    const state = slotState[slot];
    // Locked to a specific Pokemon — use exact (id, form) bundle
    if (state.locked) {
        return { id: state.locked.id, form: state.locked.form };
    }
    return buildBundleFromRows(slot);
}

function buildBundleFromRows(slot) {
    const bundle = {};
    for (const row of slotState[slot].rows) {
        if (!row.field || row.value === '' || row.value === undefined) continue;
        const cfg = FIELD_CONFIG[row.field];
        if (!cfg) continue;

        let value = row.value;
        if (value === '__null__') value = null;
        else if (cfg.input === 'integer') {
            value = parseInt(value);
            if (isNaN(value)) continue;
        }
        else if (cfg.input === 'decimal') {
            value = parseFloat(value);
            if (isNaN(value)) continue;
        }

        bundle[row.field] = value;
    }
    return Object.keys(bundle).length ? bundle : null;
}

// ---------------------------------------------------------------------------
// Filter row CRUD
// ---------------------------------------------------------------------------

function addFilterRow(slot) {
    slotState[slot].rows.push({ id: uid(), field: '', value: '' });
    renderFilterRows(slot);
    refreshSlotCount(slot);
}

function removeFilterRow(slot, rowId) {
    slotState[slot].rows = slotState[slot].rows.filter(r => r.id !== rowId);
    renderFilterRows(slot);
    refreshSlotCount(slot);
}

function onFieldChange(slot, rowId, newField) {
    const row = slotState[slot].rows.find(r => r.id === rowId);
    if (!row) return;
    row.field = newField;
    row.value = '';
    renderFilterRows(slot);
    refreshSlotCount(slot);
}

function onValueChange(slot, rowId, newValue) {
    const row = slotState[slot].rows.find(r => r.id === rowId);
    if (!row) return;
    row.value = newValue;
    refreshSlotCount(slot);
}

function renderFilterRows(slot) {
    const container = document.getElementById(`filter-rows-${slot}`);
    if (!container) return;
    container.innerHTML = '';

    slotState[slot].rows.forEach(row => {
        const rowEl = document.createElement('div');
        rowEl.className = 'filter-row';

        // Field selector
        const fieldSel = document.createElement('select');
        fieldSel.className = 'filter-field-select';
        const blank = document.createElement('option');
        blank.value = '';
        blank.textContent = '— field —';
        fieldSel.appendChild(blank);

        Object.entries(FIELD_CONFIG).forEach(([key, cfg]) => {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = cfg.label;
            if (key === row.field) opt.selected = true;
            fieldSel.appendChild(opt);
        });
        fieldSel.onchange = () => onFieldChange(slot, row.id, fieldSel.value);

        // Value input
        const valueWrap = document.createElement('div');
        valueWrap.className = 'filter-value-wrap';

        if (row.field && FIELD_CONFIG[row.field]) {
            const cfg = FIELD_CONFIG[row.field];
            let input;
            if (cfg.input === 'select') {
                input = document.createElement('select');
                input.className = 'filter-value-select';
                const ph = document.createElement('option');
                ph.value = '';
                ph.textContent = '— value —';
                input.appendChild(ph);
                cfg.options.forEach(opt => {
                    const o = document.createElement('option');
                    o.value = opt;
                    o.textContent = cfg.optionLabels?.[opt]
                        || cfg.formatOption?.(opt)
                        || capitalize(String(opt));
                    if (String(opt) === String(row.value)) o.selected = true;
                    input.appendChild(o);
                });
                input.onchange = () => onValueChange(slot, row.id, input.value);
            } else {
                input = document.createElement('input');
                input.className = 'filter-value-input';
                input.value = row.value;
                Object.entries(cfg.attrs || {}).forEach(([k, v]) => input.setAttribute(k, v));
                input.oninput = () => onValueChange(slot, row.id, input.value);
            }
            valueWrap.appendChild(input);
        } else {
            const ph = document.createElement('div');
            ph.className = 'filter-value-placeholder';
            ph.textContent = '← select field';
            valueWrap.appendChild(ph);
        }

        // Remove button
        const removeBtn = document.createElement('button');
        removeBtn.className = 'filter-row-remove';
        removeBtn.textContent = '−';
        removeBtn.title = 'Remove filter';
        removeBtn.onclick = () => removeFilterRow(slot, row.id);

        rowEl.appendChild(fieldSel);
        rowEl.appendChild(valueWrap);
        rowEl.appendChild(removeBtn);
        container.appendChild(rowEl);
    });

    // If this slot is locked, keep rows disabled after re-render
    if (slotState[slot].locked) {
        setFilterRowsDisabled(slot, true);
    }
}

// ---------------------------------------------------------------------------
// Count refresh
// ---------------------------------------------------------------------------

async function refreshSlotCount(slot) {
    if (slotState[slot].locked) {
        updateCountDisplay(slot, 1, slotState[slot]._total || null);
        updateGenerateButton();
        return;
    }
    const bundle = buildBundleFromRows(slot);
    try {
        const resp = await fetch('/api/bundle/count', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bundle }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        slotState[slot]._count = data.matched;
        slotState[slot]._total = data.total;
        updateCountDisplay(slot, data.matched, data.total);
        updateGenerateButton();
    } catch (err) {
        console.error('refreshSlotCount error:', err);
    }
}

function updateCountDisplay(slot, matched, total) {
    const el = document.getElementById(`count-${slot}`);
    if (!el) return;
    el.textContent = total != null ? `${matched} / ${total}` : `${matched}`;
    el.style.color = matched === 0
        ? 'var(--red)'
        : matched === 1
            ? 'var(--yellow)'
            : 'var(--green)';
}

// ---------------------------------------------------------------------------
// Generate button guard
// ---------------------------------------------------------------------------

function updateGenerateButton() {
    const btn = document.getElementById('generate-btn');
    const hintEl = document.getElementById('generate-hint');
    if (!btn) return;

    const stP = slotState.p;
    const stQ = slotState.q;
    const cP = stP.locked ? 1 : stP._count;
    const cQ = stQ.locked ? 1 : stQ._count;

    let disabled = false;
    let hint = '';

    if (stP.locked && stQ.locked) {
        // Both locked — only fail if same Pokemon
        if (stP.locked.id === stQ.locked.id && stP.locked.form === stQ.locked.form) {
            disabled = true;
            hint = 'Both slots are locked to the same Pokémon.';
        }
    } else if (cP === 0) {
        disabled = true;
        hint = 'Filter P has no matching Pokémon.';
    } else if (cQ === 0) {
        disabled = true;
        hint = 'Filter Q has no matching Pokémon.';
    } else if (!stP.locked && !stQ.locked) {
        // Check if bundles are identical with pool < 2
        const bp = JSON.stringify(buildBundleFromRows('p'));
        const bq = JSON.stringify(buildBundleFromRows('q'));
        if (bp === bq && cP < 2) {
            disabled = true;
            hint = 'Identical filters need at least 2 Pokémon to pick from.';
        }
    }

    btn.disabled = disabled;
    if (hint) {
        hintEl.textContent = hint;
        hintEl.classList.remove('hidden');
    } else {
        hintEl.classList.add('hidden');
    }
}

// ---------------------------------------------------------------------------
// Search / autocomplete
// ---------------------------------------------------------------------------

const SEARCH_DEBOUNCE_MS = 300;
const searchTimers = { p: null, q: null };

function onSearchInput(slot) {
    clearTimeout(searchTimers[slot]);
    searchTimers[slot] = setTimeout(
        () => fetchAndShowCandidates(slot),
        SEARCH_DEBOUNCE_MS
    );
}

function onSearchFocus(slot) {
    fetchAndShowCandidates(slot);
}

async function fetchAndShowCandidates(slot) {
    const searchEl = document.getElementById(`search-${slot}`);
    const search = searchEl?.value || '';
    const bundle = buildBundleFromRows(slot);

    try {
        const resp = await fetch('/api/bundle/candidates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bundle, search, limit: 12 }),
        });
        if (!resp.ok) return;
        const data = await resp.json();

        slotState[slot]._count = data.matched;
        slotState[slot]._total = data.total;
        updateCountDisplay(slot, data.matched, data.total);
        updateGenerateButton();
        renderAutocomplete(slot, data.candidates, search);
    } catch (err) {
        console.error('fetchAndShowCandidates error:', err);
    }
}

function renderAutocomplete(slot, candidates, search) {
    const dropdown = document.getElementById(`autocomplete-${slot}`);
    if (!dropdown) return;

    if (!candidates.length) {
        dropdown.classList.add('hidden');
        return;
    }

    dropdown.innerHTML = '';
    candidates.forEach(p => {
        const item = document.createElement('div');
        item.className = 'autocomplete-item';

        // Name with search highlight
        const nameEl = document.createElement('span');
        nameEl.className = 'autocomplete-name';
        const displayName = p.name.replace(/-/g, ' ');
        if (search) {
            const idx = displayName.toLowerCase().indexOf(search.toLowerCase());
            if (idx >= 0) {
                nameEl.innerHTML =
                    escapeHtml(displayName.slice(0, idx)) +
                    `<mark>${escapeHtml(displayName.slice(idx, idx + search.length))}</mark>` +
                    escapeHtml(displayName.slice(idx + search.length));
            } else {
                nameEl.textContent = displayName;
            }
        } else {
            nameEl.textContent = displayName;
        }

        // Meta info
        const metaEl = document.createElement('span');
        metaEl.className = 'autocomplete-meta';
        metaEl.textContent = `${p.types.join('/')} · Gen ${p.generation}`;

        item.appendChild(nameEl);
        item.appendChild(metaEl);
        item.onmousedown = (e) => {
            e.preventDefault(); // prevent blur before click registers
            lockSlot(slot, p);
        };

        dropdown.appendChild(item);
    });

    dropdown.classList.remove('hidden');
}

function lockSlot(slot, pokemon) {
    slotState[slot].locked = pokemon;

    // Swap search → locked display
    document.getElementById(`search-wrap-${slot}`)?.classList.add('hidden');
    document.getElementById(`autocomplete-${slot}`)?.classList.add('hidden');

    const lockedEl = document.getElementById(`locked-${slot}`);
    const lockedName = document.getElementById(`locked-display-${slot}`);
    if (lockedEl && lockedName) {
        lockedName.textContent = pokemon.display_name;
        lockedEl.classList.remove('hidden');
    }

    // Disable filter rows and add-filter button while locked
    setFilterRowsDisabled(slot, true);

    updateCountDisplay(slot, 1, slotState[slot]._total || null);
    updateGenerateButton();
}

function clearLock(slot) {
    slotState[slot].locked = null;

    document.getElementById(`locked-${slot}`)?.classList.add('hidden');
    const searchWrap = document.getElementById(`search-wrap-${slot}`);
    searchWrap?.classList.remove('hidden');

    const searchEl = document.getElementById(`search-${slot}`);
    if (searchEl) {
        searchEl.value = '';
        searchEl.focus();
    }

    // Re-enable filter rows and add-filter button
    setFilterRowsDisabled(slot, false);

    refreshSlotCount(slot);
    fetchAndShowCandidates(slot);
}

function setFilterRowsDisabled(slot, disabled) {
    const container = document.getElementById(`filter-rows-${slot}`);
    const addBtn = document.querySelector(`#filter-slot-${slot} .btn-add-filter`);

    if (container) {
        container.querySelectorAll('select, input, button').forEach(el => {
            el.disabled = disabled;
        });
        container.style.opacity = disabled ? '0.4' : '1';
    }

    if (addBtn) {
        addBtn.disabled = disabled;
        addBtn.style.opacity = disabled ? '0.4' : '1';
        addBtn.style.cursor = disabled ? 'not-allowed' : 'pointer';
    }
}

// Close autocomplete when clicking outside
document.addEventListener('click', (e) => {
    ['p', 'q'].forEach(slot => {
        const wrap = document.getElementById(`search-wrap-${slot}`);
        if (wrap && !wrap.contains(e.target)) {
            document.getElementById(`autocomplete-${slot}`)?.classList.add('hidden');
        }
    });
});

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
            body: JSON.stringify({
                bundle_p: buildBundle('p'),
                bundle_q: buildBundle('q'),
            }),
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
// State machine
// ---------------------------------------------------------------------------

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

function applyStateMismatch(errorMsg) {
    setIndicator('partial', 'Key mismatch');
    hide('key-info');
    show('key-message');
    setMessage(
        errorMsg || 'Key mismatch — these keys don\'t work together. Purge and re-upload both files.',
        'error'
    );
    show('purge-btn');
    hide('key-divider');
    hide('upload-section');
    hide('generate-section');
    setSlot('private', true);
    setSlot('public', true);
    enablePanels(false);
    setStatus('Key mismatch — purge and re-upload.', 'error');
}

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
// Upload
// ---------------------------------------------------------------------------

async function handleUpload(which, input) {
    const file = input.files[0];
    if (!file) return;

    const formKey = which === 'private' ? 'private_key' : 'public_key';
    const form = new FormData();
    form.append(formKey, file);

    setSlot(which, false);
    setStatus('Uploading…', 'working');

    try {
        const resp = await fetch('/api/session/keys', { method: 'POST', body: form });
        const data = await resp.json();

        if (!resp.ok) {
            setStatus(data.error, 'error');
            input.value = '';
            return;
        }

        if (data.saved === 'private_key') setSlot('private', true);
        if (data.saved === 'public_key') setSlot('public', true);

        if (data.state === 'partial') {
            applyStatePartial(data.has_private, data.has_public);
            setStatus(`${which === 'private' ? 'private.key' : 'public.json'} uploaded.`);
        } else if (data.state === 'both') {
            setStatus('Validating key pair…', 'working');
            await validateKeys();
        }
    } catch (err) {
        setStatus(`Upload error: ${err.message}`, 'error');
        input.value = '';
    }
}

// ---------------------------------------------------------------------------
// Validate
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
        document.getElementById('upload-private').value = '';
        document.getElementById('upload-public').value = '';
    } catch (err) {
        setStatus(`Purge error: ${err.message}`, 'error');
    }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function refreshKeyStatus() {
    try {
        const resp = await fetch('/api/session/status');
        const data = await resp.json();
        if (data.state === 'empty') applyStateEmpty();
        else if (data.state === 'partial') applyStatePartial(data.has_private, data.has_public);
        else if (data.state === 'both') await validateKeys();
    } catch (err) {
        console.error('refreshKeyStatus error:', err);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    refreshKeyStatus();
    refreshSlotCount('p');
    refreshSlotCount('q');
});