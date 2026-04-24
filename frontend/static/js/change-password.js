function initChangePasswordModal() {
    if (document.getElementById('change-password-modal')) return;

    const modal = document.createElement('div');
    modal.id = 'change-password-modal';
    modal.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;';
    modal.innerHTML = `
        <div style="background:#44444A;border:1px solid rgba(201,169,110,0.22);max-width:400px;width:90%;padding:2rem;position:relative;">
            <button onclick="closePasswordModal()" style="position:absolute;top:0.75rem;right:1rem;background:none;border:none;color:#aaa;font-size:1.5rem;cursor:pointer;">&times;</button>
            <h2 style="font-family:'EB Garamond',serif;font-style:italic;font-size:1.5rem;color:#F0EDE8;margin:0 0 0.25rem;">Change Password</h2>
            <p style="font-size:0.75rem;color:#888;margin-bottom:1.5rem;font-family:'Roboto',sans-serif;letter-spacing:0.08em;">Enter your current password and choose a new one</p>
            <div style="margin-bottom:1rem;">
                <label style="display:block;font-size:0.7rem;color:#aaa;text-transform:uppercase;letter-spacing:0.12em;margin-bottom:0.35rem;font-family:'Roboto',sans-serif;">Current Password</label>
                <input type="password" id="cp-current" style="width:100%;padding:0.6rem 0.75rem;background:#38383B;border:1px solid rgba(201,169,110,0.15);color:#F0EDE8;font-size:0.9rem;box-sizing:border-box;" autocomplete="current-password">
            </div>
            <div style="margin-bottom:1rem;">
                <label style="display:block;font-size:0.7rem;color:#aaa;text-transform:uppercase;letter-spacing:0.12em;margin-bottom:0.35rem;font-family:'Roboto',sans-serif;">New Password</label>
                <input type="password" id="cp-new" style="width:100%;padding:0.6rem 0.75rem;background:#38383B;border:1px solid rgba(201,169,110,0.15);color:#F0EDE8;font-size:0.9rem;box-sizing:border-box;" autocomplete="new-password">
            </div>
            <div style="margin-bottom:1.25rem;">
                <label style="display:block;font-size:0.7rem;color:#aaa;text-transform:uppercase;letter-spacing:0.12em;margin-bottom:0.35rem;font-family:'Roboto',sans-serif;">Confirm New Password</label>
                <input type="password" id="cp-confirm" style="width:100%;padding:0.6rem 0.75rem;background:#38383B;border:1px solid rgba(201,169,110,0.15);color:#F0EDE8;font-size:0.9rem;box-sizing:border-box;" autocomplete="new-password">
            </div>
            <div id="cp-error" style="display:none;color:#ff6b6b;font-size:0.82rem;margin-bottom:1rem;font-family:'Roboto',sans-serif;"></div>
            <div id="cp-success" style="display:none;color:#4ecdc4;font-size:0.82rem;margin-bottom:1rem;font-family:'Roboto',sans-serif;"></div>
            <button id="cp-submit-btn" onclick="submitPasswordChange()" style="width:100%;padding:0.7rem;background:#C9A96E;color:#1e1e20;border:none;font-family:'Roboto',sans-serif;font-size:0.85rem;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;cursor:pointer;">Change Password</button>
        </div>`;
    document.body.appendChild(modal);

    modal.addEventListener('click', function(e) {
        if (e.target === modal) closePasswordModal();
    });
}

function openPasswordModal() {
    initChangePasswordModal();
    const modal = document.getElementById('change-password-modal');
    modal.style.display = 'flex';
    document.getElementById('cp-current').value = '';
    document.getElementById('cp-new').value = '';
    document.getElementById('cp-confirm').value = '';
    document.getElementById('cp-error').style.display = 'none';
    document.getElementById('cp-success').style.display = 'none';
    document.getElementById('cp-submit-btn').disabled = false;
    document.getElementById('cp-submit-btn').textContent = 'Change Password';
    document.getElementById('cp-current').focus();
}

function closePasswordModal() {
    document.getElementById('change-password-modal').style.display = 'none';
}

async function submitPasswordChange() {
    const current = document.getElementById('cp-current').value;
    const newPw = document.getElementById('cp-new').value;
    const confirm = document.getElementById('cp-confirm').value;
    const errEl = document.getElementById('cp-error');
    const successEl = document.getElementById('cp-success');
    const btn = document.getElementById('cp-submit-btn');

    errEl.style.display = 'none';
    successEl.style.display = 'none';

    if (!current) { errEl.textContent = 'Enter your current password'; errEl.style.display = 'block'; return; }
    if (newPw.length < 10) { errEl.textContent = 'Password must be at least 10 characters with uppercase, lowercase, digit, and special character'; errEl.style.display = 'block'; return; }
    if (newPw !== confirm) { errEl.textContent = 'New passwords do not match'; errEl.style.display = 'block'; return; }

    btn.disabled = true;
    btn.textContent = 'Changing...';

    try {
        const token = sessionStorage.getItem('bmm_token');
        const res = await fetch('/api/v1/vendors/me/change-password', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: current, new_password: newPw })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to change password');
        successEl.textContent = 'Password changed successfully!';
        successEl.style.display = 'block';
        btn.textContent = 'Done';
        setTimeout(closePasswordModal, 1500);
    } catch (e) {
        errEl.textContent = e.message;
        errEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Change Password';
    }
}
