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
