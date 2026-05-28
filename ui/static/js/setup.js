// setup.js — DB initialization page logic

function startSeed() {
    const mode = document.querySelector('input[name="seed_mode"]:checked')?.value;
    if (!mode) return;

    const gens = [...document.querySelectorAll('input[name="gen"]:checked')]
        .map(el => parseInt(el.value));

    if (mode === 'gen' && gens.length === 0) {
        alert('Please select at least one generation.');
        return;
    }

    // Switch to progress view
    document.getElementById('setup-form').classList.add('hidden');
    document.getElementById('progress-card').classList.remove('hidden');

    const log = document.getElementById('progress-log');
    const bar = document.getElementById('progress-bar');
    const countEl = document.getElementById('progress-count');
    const launchBtn = document.getElementById('launch-btn');

    const evtSource = new EventSource('/api/setup/seed?' + new URLSearchParams({
        _t: Date.now()
    }));

    // Kick off via POST first, then SSE for progress
    fetch('/api/setup/seed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, gens }),
    });

    // We use SSE from the POST response stream — re-open as EventSource
    // Actually: POST returns SSE stream, so we use fetch + ReadableStream
    evtSource.close();

    streamSeed(mode, gens, log, bar, countEl, launchBtn);
}

async function streamSeed(mode, gens, log, bar, countEl, launchBtn) {
    try {
        const resp = await fetch('/api/setup/seed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, gens }),
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let insertedCount = 0;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const msg = line.slice(5).trim();

                if (msg.startsWith('DONE:')) {
                    const count = msg.split(':')[1];
                    countEl.textContent = `${count} records`;
                    bar.classList.add('done');
                    log.textContent += `\n✓ Done. ${count} Pokemon in database.\n`;
                    log.scrollTop = log.scrollHeight;
                    launchBtn.classList.remove('hidden');
                    return;
                }

                if (msg.startsWith('ERROR:')) {
                    const errMsg = msg.slice(6);
                    log.textContent += `\n✗ Error: ${errMsg}\n`;
                    bar.style.background = 'var(--red)';
                    bar.classList.add('done');
                    return;
                }

                if (msg) {
                    log.textContent += msg + '\n';
                    log.scrollTop = log.scrollHeight;

                    // Rough progress animation based on inserted lines
                    if (msg.includes('✓') || msg.startsWith('[')) {
                        insertedCount++;
                        const pct = Math.min(95, insertedCount * 2);
                        bar.style.width = pct + '%';
                    }
                }
            }
        }
    } catch (err) {
        document.getElementById('progress-log').textContent += `\n✗ Connection error: ${err}\n`;
    }
}