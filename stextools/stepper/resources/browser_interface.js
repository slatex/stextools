async function fetchUpdates() {
    const response = await fetch('/fetch');
    const data = await response.json();
    const contentDiv = document.getElementById('content');
    data.elements.forEach(element => {
        if (element.type === 'html') {
            const span = document.createElement('span');
            span.innerHTML = element.html;
            contentDiv.appendChild(span);
            // TODO: snify-specific code shouldn't be here
            const target = document.getElementById("snifyhighlight")
            if (target) {
                target.scrollIntoView({behavior: "smooth", block: "center"});
            }
        } else if (element.type === 'input') {
            const input = document.createElement('input');
            input.type = 'text';
            input.style.fontFamily = 'monospace';
            input.style.width = '10em';
            input.style.backgroundColor = '#eeeeee';
            input.onkeydown = async function (event) {
                if (event.key === 'Enter') {
                    const value = input.value;
                    input.disabled = true;
                    const response = await fetch('/input', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'text/plain',
                        },
                        body: value,
                    });
                    if (response.ok) {
                        const br = document.createElement('br');
                        contentDiv.appendChild(br);
                    } else {
                        alert('Error sending input to server.');
                    }
                }
            };
            contentDiv.appendChild(input);
            input.focus();
        } else if (element.type === 'clear') {
            contentDiv.innerHTML = '';
        } else {
            console.error('Unknown element type:', element.type);
        }
    });
    setTimeout(fetchUpdates, 50);   // poll every 50ms
}
window.onload = fetchUpdates;
