/**
 * SISTEMA DE CADASTRO - IGUALDADE ACREANA
 * Funções de Interface e Comunicação com a API
 */

// 1. MÁSCARA DE CPF (000.000.000-00)
function mascaraCPF(i) {
    let v = i.value.replace(/\D/g, ""); 
    if (v.length <= 11) {
        v = v.replace(/(\d{3})(\d)/, "$1.$2");
        v = v.replace(/(\d{3})(\d)/, "$1.$2");
        v = v.replace(/(\d{3})(\d{1,2})$/, "$1-$2");
    }
    i.value = v;
}

// 2. MÁSCARA DE CEP (00000-000)
function mascaraCEP(i) {
    let v = i.value.replace(/\D/g, "");
    if (v.length > 5) {
        v = v.substring(0, 5) + "-" + v.substring(5, 8);
    }
    i.value = v;
}

// 3. BUSCA AUTOMÁTICA DE CEP (VIA CEP)
async function buscarCEP(valor) {
    const cep = valor.replace(/\D/g, "");
    const loader = document.getElementById('loader-cep');

    if (cep.length === 8) {
        loader.classList.remove('hidden'); // Mostra spinner
        
        try {
            const resposta = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
            const dados = await resposta.json();

            if (!dados.erro) {
                document.getElementById('logradouro').value = dados.logradouro.toUpperCase();
                document.getElementById('bairro').value = dados.bairro.toUpperCase();
                document.getElementById('cidade').value = dados.localidade.toUpperCase();
                document.getElementById('estado').value = dados.uf.toUpperCase();
                
                // Remove o readonly para permitir ajustes se necessário e foca no número
                document.getElementById('logradouro').readOnly = false;
                document.getElementById('numero').focus();
            } else {
                alert("CEP NÃO ENCONTRADO.");
            }
        } catch (erro) {
            console.error("Erro na busca do CEP:", erro);
        } finally {
            loader.classList.add('hidden'); // Esconde spinner
        }
    }
}

// 4. ADICIONAR CAMPOS DE FAMILIAR DINAMICAMENTE
function adicionarCampoFamiliar() {
    const container = document.getElementById('lista-familiares');
    const div = document.createElement('div');
    div.className = "p-4 bg-blue-50 rounded-xl border border-blue-100 relative mb-4 shadow-sm animate-fade-in";
    
    div.innerHTML = `
        <select class="tipo-familiar w-full p-3 mb-3 rounded-lg border-blue-200 text-blue-900 font-bold bg-white outline-none focus:ring-2 focus:ring-blue-400">
            <option value="Cunhada">CUNHADA</option>
            <option value="Sobrinho">SOBRINHO</option>
            <option value="Sobrinha">SOBRINHA</option>
        </select>
        <input type="text" class="nome-familiar w-full p-3 mb-3 rounded-lg border-blue-200 uppercase outline-none focus:ring-2 focus:ring-blue-400" placeholder="NOME DO FAMILIAR">
        <div class="flex flex-col">
            <label class="text-[10px] font-bold text-blue-600 ml-1 mb-1">DATA DE NASCIMENTO</label>
            <input type="date" class="data-familiar w-full p-3 rounded-lg border-blue-200 bg-white text-blue-900 outline-none">
        </div>
        <button type="button" onclick="this.parentElement.remove()" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full w-8 h-8 flex items-center justify-center font-bold shadow-md border-2 border-white">×</button>
    `;
    container.appendChild(div);
}

// 5. ENVIO DOS DADOS PARA O RENDER (BACKEND)
async function enviarDados() {
    const btn = document.getElementById('btnSalvar');
    const originalText = btn.innerText;
    
    btn.disabled = true;
    btn.innerText = "PROCESSANDO...";

    // Coleta e Higienização dos Dados (Tudo em Maiúsculas onde aplicável)
    const dados = {
        nome: document.getElementById('nome').value.toUpperCase(),
        cim: document.getElementById('cim').value.replace(/\D/g, ""), // Apenas números
        cpf: document.getElementById('cpf').value,
        data_nascimento: document.getElementById('data_nascimento').value || null,
        
        // Datas Maçônicas
        data_iniciacao: document.getElementById('data_iniciacao').value || null,
        data_elevacao: document.getElementById('data_elevacao').value || null,
        data_exaltacao: document.getElementById('data_exaltacao').value || null,
        data_filiacao: document.getElementById('data_filiacao').value || null,
        data_afastamento: document.getElementById('data_afastamento').value || null,

        // Endereço
        cep: document.getElementById('cep').value,
        logradouro: document.getElementById('logradouro').value.toUpperCase(),
        numero: document.getElementById('numero').value.replace(/\D/g, ""), // Apenas números
        bairro: document.getElementById('bairro').value.toUpperCase(),
        cidade: document.getElementById('cidade').value.toUpperCase(),
        estado: document.getElementById('estado').value.toUpperCase(),
        
        familiares: []
    };

    // Coleta os familiares da lista dinâmica
    const blocosFamiliares = document.querySelectorAll('#lista-familiares > div');
    blocosFamiliares.forEach(bloco => {
        const nomeFam = bloco.querySelector('.nome-familiar').value;
        if (nomeFam) { // Só adiciona se o nome estiver preenchido
            dados.familiares.push({
                tipo_parentesco: bloco.querySelector('.tipo-familiar').value,
                nome: nomeFam.toUpperCase(),
                data_nascimento: bloco.querySelector('.data-familiar').value || null
            });
        }
    });

    try {
        // --- SUBSTITUA PELA SUA URL DO RENDER ---
        const urlAPI = 'https://seu-projeto-no-render.onrender.com/obreiros/';
        
        const resposta = await fetch(urlAPI, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dados)
        });

        if (resposta.ok) {
            alert("CADASTRO REALIZADO COM SUCESSO!");
            window.scrollTo(0, 0);
            location.reload(); // Limpa o formulário
        } else {
            const erro = await resposta.json();
            alert("ERRO AO SALVAR: " + (erro.detail || "Verifique os dados."));
        }
    } catch (e) {
        alert("FALHA DE CONEXÃO: O servidor pode estar iniciando. Tente novamente em 30 segundos.");
        console.error(e);
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}
