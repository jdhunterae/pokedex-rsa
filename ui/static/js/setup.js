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

    // Start the seeder
    fetch('/api/setup/seed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, gens }),
    })
        .then(r => r.json())
        .then(data => {
            if (!data.started) {
                log.textContent += `\n✗ Error: ${data.error || 'Could not start seeder.'}\n`;
                return;
            }
            // Begin polling for progress
            pollProgress(log, bar, countEl, launchBtn);
        })
        .catch(err => {
            log.textContent += `\n✗ Network error: ${err.message}\n`;
        });
}

let seenLines = 0;

function pollProgress(log, bar, countEl, launchBtn) {
    fetch('/api/setup/progress')
        .then(r => r.json())
        .then(data => {
            // Append any new log lines
            const newLines = data.log.slice(seenLines);
            newLines.forEach(line => {
                log.textContent += line + '\n';
                log.scrollTop = log.scrollHeight;

                // Rough progress based on inserted records
                if (line.includes('✓') || line.match(/^\[/)) {
                    const pct = Math.min(95, parseInt(bar.style.width || '0') + 2);
                    bar.style.width = pct + '%';
                }
            });
            seenLines = data.log.length;

            if (data.error) {
                log.textContent += `\n✗ Error: ${data.error}\n`;
                bar.style.background = 'var(--red)';
                bar.classList.add('done');
                return;
            }

            if (data.done) {
                countEl.textContent = `${data.count} records`;
                bar.classList.add('done');
                log.textContent += `\n✓ Done. ${data.count} Pokemon in database.\n`;
                log.scrollTop = log.scrollHeight;
                launchBtn.classList.remove('hidden');
                return;
            }

            // Still running — poll again in 750ms
            setTimeout(() => pollProgress(log, bar, countEl, launchBtn), 750);
        })
        .catch(err => {
            log.textContent += `\n✗ Poll error: ${err.message}\n`;
        });
}