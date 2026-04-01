// 1. Máscara de CPF automática
function mascaraCPF(i) {
    let v = i.value;
    if (isNaN(v[v.length - 1])) {
        i.value = v.substring(0, v.length - 1);
        return;
    }
    i.setAttribute("maxlength", "14");
    if (v.length == 3 || v.length == 7) i.value += ".";
    if (v.length == 11) i.value += "-";
}

// 2. Adicionar Familiar com DATA DE NASCIMENTO
function adicionarCampoFamiliar() {
    const container = document.getElementById('lista-familiares');
    const div = document.createElement('div');
    div.className = "p-3 bg-blue-50 rounded-lg border border-blue-100 relative mb-4";
    
    div.innerHTML = `
        <select class="tipo-familiar w-full p-2 mb-2 rounded border-blue-200 text-blue-800 font-bold bg-white">
            <option value="Cunhada">Cunhada</option>
            <option value="Sobrinho">Sobrinho</option>
            <option value="Sobrinha">Sobrinha</option>
        </select>
        <input type="text" class="nome-familiar w-full p-2 mb-2 rounded border-blue-200 uppercase" placeholder="NOME DO FAMILIAR">
        <div class="flex flex-col">
            <label class="text-[10px] text-blue-600 ml-1">DATA DE NASCIMENTO</label>
            <input type="date" class="data-familiar w-full p-2 rounded border-blue-200 bg-white text-gray-500">
        </div>
        <button type="button" onclick="this.parentElement.remove()" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-6 h-6 flex items-center justify-center font-bold">×</button>
    `;
    container.appendChild(div);
}

// 3. Envio com conversão para MAIÚSCULAS (.toUpperCase())
async function enviarDados() {
    const btn = document.getElementById('btnSalvar');
    btn.disabled = true;
    btn.innerText = "SALVANDO...";

    const dados = {
        // Dados Pessoais em MAIÚSCULAS
        nome: document.getElementById('nome').value.toUpperCase(),
        cim: document.getElementById('cim').value,
        cpf: document.getElementById('cpf').value,
        data_nascimento: document.getElementById('data_nascimento').value || null,
        
        // Datas Maçônicas
        data_iniciacao: document.getElementById('data_iniciacao').value || null,
        data_elevacao: document.getElementById('data_elevacao').value || null,
        data_exaltacao: document.getElementById('data_exaltacao').value || null,
        data_filiacao: document.getElementById('data_filiacao').value || null,
        data_afastamento: document.getElementById('data_afastamento').value || null,

        // Endereço em MAIÚSCULAS
        cep: document.getElementById('cep').value,
        logradouro: document.getElementById('logradouro').value.toUpperCase(),
        numero: document.getElementById('numero').value.toUpperCase(),
        bairro: document.getElementById('bairro').value.toUpperCase(),
        cidade: document.getElementById('cidade').value.toUpperCase(),
        estado: document.getElementById('estado').value.toUpperCase(),
        
        familiares: []
    };

    // Coleta Familiares
    const blocos = document.querySelectorAll('#lista-familiares > div');
    blocos.forEach(bloco => {
        dados.familiares.push({
            tipo_parentesco: bloco.querySelector('.tipo-familiar').value,
            nome: bloco.querySelector('.nome-familiar').value.toUpperCase(),
            data_nascimento: bloco.querySelector('.data-familiar').value || null
        });
    });

    try {
        const resposta = await fetch('SUA_URL_DO_RENDER_AQUI/obreiros/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dados)
        });

        if (resposta.ok) {
            alert("CADASTRO REALIZADO COM SUCESSO!");
            location.reload();
        } else {
            alert("ERRO AO SALVAR. VERIFIQUE OS DADOS.");
        }
    } catch (e) {
        alert("FALHA NA CONEXÃO COM O SERVIDOR.");
    } finally {
        btn.disabled = false;
        btn.innerText = "SALVAR CADASTRO";
    }
}
