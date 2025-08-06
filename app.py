import streamlit as st
import pandas as pd
from datetime import datetime
import os

# --- Configuração da Página ---
st.set_page_config(page_title="Atualização de Projetos", page_icon="⚡", layout="wide")

st.title("🔄 Atualização de Projeto - 77 COS")

st.markdown("Preencha as informações abaixo para registrar uma atualização de projeto.")

# --- Função para salvar dados ---
def salvar_dados(dados, nome_arquivo="atualizacoes_projetos.csv"):
    # Verifica se o arquivo já existe
    if os.path.exists(nome_arquivo):
        df_existente = pd.read_csv(nome_arquivo)
        df_atualizado = pd.concat([df_existente, dados], ignore_index=True)
    else:
        df_atualizado = dados

    df_atualizado.to_csv(nome_arquivo, index=False)

# --- Formulário de Entrada ---
with st.form("form_atualizacao"):
    st.subheader("🧾 Dados do Cliente")
    cliente = st.text_input("Nome do Cliente")
    data_envio = st.date_input("Data do Envio", value=datetime.today())
    cidade = st.text_input("Cidade")
    fase = st.selectbox("Fase da ligação", ["Monofásico", "Bifásico", "Trifásico"])
    carga_instalada = st.number_input("Carga Instalada (kW)", step=0.1)

    st.subheader("🔌 Kit Instalado")
    kit_inst_pot = st.text_input("Potência (kWp)", key="kit_inst_pot")
    kit_inst_placa = st.text_input("Placas", key="kit_inst_placa")
    kit_inst_inversor = st.text_input("Inversor", key="kit_inst_inversor")

    st.subheader("📦 Kit Enviado")
    kit_env_pot = st.text_input("Potência (kWp)", key="kit_env_pot")
    kit_env_placa = st.text_input("Placas", key="kit_env_placa")
    kit_env_inversor = st.text_input("Inversor", key="kit_env_inversor")

    comentario_notion = st.text_area("Comentário do Notion")

    st.subheader("⚡ Kit Atual Instalado")
    kit_atual_pot = st.text_input("Potência (kWp)", key="kit_atual_pot")
    kit_atual_placa = st.text_input("Placas", key="kit_atual_placa")
    kit_atual_inversor = st.text_input("Inversor", key="kit_atual_inversor")

    st.subheader("📝 Observação (Cole aqui o resultado do outro app)")
    observacao = st.text_area("Observação")

    submitted = st.form_submit_button("✅ Salvar Atualização")

    if submitted:
        nova_linha = pd.DataFrame([{
            "Cliente": cliente,
            "Data de Envio": data_envio,
            "Cidade": cidade,
            "Fase": fase,
            "Carga Instalada": carga_instalada,
            "Kit Instalado - Potência": kit_inst_pot,
            "Kit Instalado - Placas": kit_inst_placa,
            "Kit Instalado - Inversor": kit_inst_inversor,
            "Kit Enviado - Potência": kit_env_pot,
            "Kit Enviado - Placas": kit_env_placa,
            "Kit Enviado - Inversor": kit_env_inversor,
            "Comentário do Notion": comentario_notion,
            "Kit Atual - Potência": kit_atual_pot,
            "Kit Atual - Placas": kit_atual_placa,
            "Kit Atual - Inversor": kit_atual_inversor,
            "Observação": observacao,
        }])

        salvar_dados(nova_linha)
        st.success("✅ Atualização salva com sucesso!")

# --- Visualização dos dados já salvos ---
if os.path.exists("atualizacoes_projetos.csv"):
    st.subheader("📋 Histórico de Atualizações")
    df = pd.read_csv("atualizacoes_projetos.csv")
    st.dataframe(df)
