document.addEventListener('DOMContentLoaded', function() {
    const taskForm = document.getElementById('taskForm');
    const taskInput = document.getElementById('taskInput');
    const submitBtn = document.getElementById('submitBtn');
    const resultSection = document.getElementById('resultSection');
    const resultContent = document.getElementById('resultContent');
    const errorSection = document.getElementById('errorSection');
    const errorContent = document.getElementById('errorContent');

    taskForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const task = taskInput.value.trim();
        if (!task) return;

        // Reset UI
        resultSection.style.display = 'none';
        errorSection.style.display = 'none';
        submitBtn.disabled = true;
        submitBtn.classList.add('loading');

        try {
            const response = await fetch('/api/execute-task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ task: task })
            });

            const data = await response.json();

            if (data.success) {
                resultContent.textContent = data.result;
                resultSection.style.display = 'block';
            } else {
                errorContent.textContent = data.error || 'An error occurred';
                errorSection.style.display = 'block';
            }
        } catch (error) {
            errorContent.textContent = 'Failed to connect to the server: ' + error.message;
            errorSection.style.display = 'block';
        } finally {
            submitBtn.disabled = false;
            submitBtn.classList.remove('loading');
        }
    });

    // Auto-resize textarea
    taskInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = this.scrollHeight + 'px';
    });
});