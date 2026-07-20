(function () {
    let authorModalLastFocus = null;
    let authorModalCloseTimer = null;

    function getAuthorModal() {
        return document.getElementById('author-list-modal');
    }

    function openAuthorModal() {
        const modal = getAuthorModal();
        if (!modal || !modal.hidden) return;

        window.clearTimeout(authorModalCloseTimer);
        authorModalLastFocus = document.activeElement;
        modal.hidden = false;
        document.body.classList.add('author-list-modal-open');
        window.requestAnimationFrame(function () {
            modal.classList.add('is-open');
            modal.querySelector('.author-list-close')?.focus();
        });
    }

    function closeAuthorModal() {
        const modal = getAuthorModal();
        if (!modal || modal.hidden) return;

        modal.classList.remove('is-open');
        document.body.classList.remove('author-list-modal-open');
        authorModalCloseTimer = window.setTimeout(function () {
            modal.hidden = true;
            if (authorModalLastFocus instanceof HTMLElement) {
                authorModalLastFocus.focus();
            }
        }, 220);
    }

    function keepFocusInsideAuthorModal(event) {
        const modal = getAuthorModal();
        if (!modal || modal.hidden || event.key !== 'Tab') return;

        const focusable = Array.from(modal.querySelectorAll('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-author-list-open]').forEach(function (button) {
            button.addEventListener('click', openAuthorModal);
        });
        document.querySelectorAll('[data-author-list-close]').forEach(function (button) {
            button.addEventListener('click', closeAuthorModal);
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') closeAuthorModal();
            keepFocusInsideAuthorModal(event);
        });

        if (new URLSearchParams(window.location.search).get('authors') === '1') {
            openAuthorModal();
        }
    });
})();
