function getWriteUrl(userId, username) {
    if (username && username !== 'null' && username !== 'undefined' && username.trim() !== '') {
        return 'https://t.me/' + username;
    }
    return 'tg://user?id=' + userId;
}

function patchWriteButtons() {
    const writeButtons = document.querySelectorAll('a.write-btn, button.write-btn, [data-write-btn]');
    writeButtons.forEach(btn => {
        const userId = btn.getAttribute('data-user-id');
        const username = btn.getAttribute('data-username');
        if (userId) {
            const url = getWriteUrl(userId, username);
            if (btn.tagName === 'A') {
                btn.href = url;
            } else {
                btn.onclick = () => { window.open(url, '_blank'); };
            }
        }
    });
}

const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
        if (mutation.addedNodes.length > 0) {
            patchWriteButtons();
        }
    });
});

document.addEventListener('DOMContentLoaded', function() {
    observer.observe(document.body, { childList: true, subtree: true });
    patchWriteButtons();
});

window.getWriteUrl = getWriteUrl;
window.patchWriteButtons = patchWriteButtons;
