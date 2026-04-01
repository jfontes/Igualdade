async function enviarDados() {
    const btn = document.getElementById('btnSalvar');
    btn.disabled = true;
    btn.innerText = "ENVIANDO...";

    const dados = {
        nome: document.getElementById('nome').value,
        cim: document.getElementById('cim').value,
        cpf: document.getElementById('cpf').value,
        data_iniciacao: document.getElementById('data_iniciacao').value,
        // ... capture todos os outros campos aqui
    };

    try {
        // SUBSTITUA pela URL que o Render te forneceu
        const resposta = await fetch('https://seu-app.onrender.com/obreiros/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dados)
        });

        if (resposta.ok) {
            alert("Cadastro realizado com sucesso!");
            location.reload(); // Limpa o formulário
        }
    } catch (erro) {
        alert("Erro ao conectar com o servidor.");
    } finally {
        btn.disabled = false;
        btn.innerText = "SALVAR CADASTRO";
    }
}

// Função para criar os campos visualmente no celular
function adicionarCampoFamiliar() {
    const container = document.getElementById('lista-familiares');
    const div = document.createElement('div');
    div.className = "p-3 bg-blue-50 rounded-lg border border-blue-100 relative animate-fade-in";
    
    div.innerHTML = `
        <select class="tipo-familiar w-full p-2 mb-2 rounded border-blue-200 text-blue-800 font-semibold">
            <option value="Cunhada">Cunhada</option>
            <option value="Sobrinho">Sobrinho</option>
            <option value="Sobrinha">Sobrinha</option>
        </select>
        <input type="text" class="nome-familiar w-full p-2 rounded border-blue-200" placeholder="Nome Completo">
        <button type="button" onclick="this.parentElement.remove()" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-6 h-6 text-xs">X</button>
    `;
    container.appendChild(div);
}

// Função de envio atualizada para capturar os familiares
async function enviarDados() {
    // Coleta dados do Obreiro
    const dados = {
        nome: document.getElementById('nome').value,
        cim: document.getElementById('cim').value,
        cpf: document.getElementById('cpf').value,
        // ... demais campos ...
        familiares: []
    };

    // Coleta todos os familiares adicionados dinamicamente
    const blocos = document.querySelectorAll('#lista-familiares > div');
    blocos.forEach(bloco => {
        dados.familiares.push({
            tipo_parentesco: bloco.querySelector('.tipo-familiar').value,
            nome: bloco.querySelector('.nome-familiar').value
        });
    });

    console.log("Enviando para o Render:", dados);
    // Aqui segue o comando fetch que vimos antes...
}
