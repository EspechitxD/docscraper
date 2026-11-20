# Instalação

## Desenvolvimento

O caminho testado neste ambiente Linux está no README. O backend precisa de `CPMH_API_TOKEN`. Sem o token o processo não inicia.

Dependências de sistema usadas aqui:

- Python 3.12 e `python3.12-venv`
- Tesseract 5.3.4 com `por`, `eng`, `chi_sim`, `chi_tra` e `osd`
- Google Chrome em `/usr/local/bin/google-chrome`
- Node.js 22.23.4

As bibliotecas Python pinadas estão em `requirements.txt`.

## Aplicativo desktop

`npm run dev` compila o processo Electron, sobe o Vite e abre a janela. O Electron escolhe a porta, gera o token e inicia `backend/.venv/bin/python -m cpmh_backend`.

`npm start` gera a interface estática e abre a janela carregando essa interface pelo próprio backend.

## Instalador Windows

`package.json` configura o electron-builder para NSIS x64:

- assistente, não instalação de um clique;
- atalho na área de trabalho e no menu Iniciar;
- ícone `assets/icons/cpmh.ico`;
- dados do usuário preservados na desinstalação.

O comando previsto é `npm run dist:win`. Ele não foi executado. Esta máquina é Linux x64 e não há Windows 10 ou 11 disponível. Por isso o diagnóstico expõe `windows_installer_tested: false` e este documento não declara compatibilidade com Windows.

O pacote ainda não embute um interpretador Python congelado. No desenvolvimento o Electron usa o virtualenv do repositório. Num instalador de usuário final, o binário do backend precisaria ser produzido no próprio Windows e colocado em `resources/backend/cpmh-backend.exe`. Esse passo não foi feito.

## Diagnóstico e reparo

A tela Diagnóstico lê versão, banco, disco, Tesseract, Chrome, Playwright e Argos. “Reparar pastas” recria os diretórios de dados. “Backup do banco” copia o SQLite. O relatório técnico pode ser baixado sem o texto dos documentos.

Na abertura, o backend também faz um backup diário e recupera tarefas interrompidas.
