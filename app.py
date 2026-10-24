import threading
import queue
import requests
import pandas as pd
import customtkinter as ctk
from tkinter import messagebox

# Configurazione grafica
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Costanti di EVE Online
JITA_STATION_ID = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
REGION_ID = 10000002        # The Forge
ESI_BASE_URL = "https://esi.evetech.net/latest"

class EveJitaTraderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("EVE Online - Jita Smart Trade Finder")
        self.geometry("1100x700")

        self.queue = queue.Queue()

        # Layout Principale
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- PANNELLO INPUT ---
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=0, column=0, padx=20, pady=10, sticky="ew")

        # Budget
        self.lbl_budget = ctk.CTkLabel(self.input_frame, text="Budget (ISK):")
        self.lbl_budget.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.ent_budget = ctk.CTkEntry(self.input_frame, width=150)
        self.ent_budget.insert(0, "1000000000") # Default 1 Bilione
        self.ent_budget.grid(row=0, column=1, padx=10, pady=10)

        # ROI Target (%)
        self.lbl_roi = ctk.CTkLabel(self.input_frame, text="ROI Minimo (%):")
        self.lbl_roi.grid(row=0, column=2, padx=10, pady=10, sticky="w")
        self.ent_roi = ctk.CTkEntry(self.input_frame, width=80)
        self.ent_roi.insert(0, "5.0")
        self.ent_roi.grid(row=0, column=3, padx=10, pady=10)

        # Tasse Totali (%)
        self.lbl_tax = ctk.CTkLabel(self.input_frame, text="Tasse Totali (%):")
        self.lbl_tax.grid(row=0, column=4, padx=10, pady=10, sticky="w")
        self.ent_tax = ctk.CTkEntry(self.input_frame, width=80)
        self.ent_tax.insert(0, "3.0") # Broker Fee + Sales Tax
        self.ent_tax.grid(row=0, column=5, padx=10, pady=10)

        # Pulsante Avvio Analisi
        self.btn_fetch = ctk.CTkButton(self.input_frame, text="Analizza Mercato Jita", command=self.start_analysis_thread)
        self.btn_fetch.grid(row=0, column=6, padx=20, pady=10)

        # --- TABELLA RISULTATI ---
        self.results_frame = ctk.CTkFrame(self)
        self.results_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        self.results_frame.grid_rowconfigure(0, weight=1)
        self.results_frame.grid_columnconfigure(0, weight=1)

        self.txt_output = ctk.CTkTextbox(self.results_frame, wrap="none", font=("Consolas", 12))
        self.txt_output.grid(row=0, column=0, sticky="nsew")

        self.txt_output.insert("0.0", "Benvenuto! Inserisci i parametri e clicca su 'Analizza Mercato Jita' per scansionare gli ordini.\n"
                                     "Nota: L'operazione richiede il download di dati dalle API ESI e potrebbe impiegare circa 30-60 secondi.")

    def start_analysis_thread(self):
        self.btn_fetch.configure(state="disabled")
        self.txt_output.delete("0.0", "end")
        self.txt_output.insert("0.0", "Scaricamento dei dati dal mercato di Jita in corso... Attendere.\n")
        
        threading.Thread(target=self.fetch_and_calculate_market, daemon=True).start()

    def fetch_and_calculate_market(self):
        try:
            budget = float(self.ent_budget.get())
            min_roi = float(self.ent_roi.get())
            tax_rate = float(self.ent_tax.get()) / 100.0
        except ValueError:
            messagebox.showerror("Errore", "Controlla che i campi numerici siano validi.")
            self.btn_fetch.configure(state="normal")
            return

        try:
            # Scarico ordini di Jita
            orders_url = f"{ESI_BASE_URL}/markets/{REGION_ID}/orders/?datasource=tranquility&order_type=all"
            response = requests.get(orders_url)
            if response.status_code != 200:
                raise Exception(f"Errore API ESI (Ordini): {response.status_code}")
            
            orders = response.json()
            jita_orders = [o for o in orders if o.get('location_id') == JITA_STATION_ID]

            if not jita_orders:
                self.txt_output.insert("end", "Nessun ordine trovato o errore di connessione.\n")
                self.btn_fetch.configure(state="normal")
                return

            df = pd.DataFrame(jita_orders)

            buy_df = df[df['is_buy_order'] == True]
            sell_df = df[df['is_buy_order'] == False]

            best_buy = buy_df.groupby('type_id')['price'].max().reset_index()
            best_buy.rename(columns={'price': 'max_buy_price'}, inplace=True)

            best_sell = sell_df.groupby('type_id')['price'].min().reset_index()
            best_sell.rename(columns={'price': 'min_sell_price'}, inplace=True)

            sell_volumes = sell_df.groupby('type_id')['volume_remain'].sum().reset_index()
            sell_volumes.rename(columns={'volume_remain': 'sell_volume_available'}, inplace=True)

            buy_volumes = buy_df.groupby('type_id')['volume_remain'].sum().reset_index()
            buy_volumes.rename(columns={'volume_remain': 'buy_volume_required'}, inplace=True)

            market_summary = pd.merge(best_sell, best_buy, on='type_id', how='inner')
            market_summary = pd.merge(market_summary, sell_volumes, on='type_id', how='inner')
            market_summary = pd.merge(market_summary, buy_volumes, on='type_id', how='inner')

            # Recupero dei nomi degli item
            self.txt_output.insert("end", "Download dei nomi degli oggetti in corso...\n")
            names_map = self.get_item_names(market_summary['type_id'].tolist())

            market_summary['item_name'] = market_summary['type_id'].map(names_map)

            # Calcoli ROI e margini (Station trading: acquisto con Buy Order, vendita con Sell Order)
            market_summary['net_revenue'] = market_summary['min_sell_price'] * (1 - tax_rate)
            market_summary['unit_profit'] = market_summary['net_revenue'] - market_summary['max_buy_price']
            market_summary['roi'] = (market_summary['unit_profit'] / market_summary['max_buy_price']) * 100

            filtered = market_summary[
                (market_summary['max_buy_price'] <= budget) & 
                (market_summary['roi'] >= min_roi) &
                (market_summary['unit_profit'] > 0)
            ].sort_values(by='roi', ascending=False)

            output_str = f"{'Nome Item':<35} | {'Costo Buy (ISK)':<20} | {'Vendita Sell (ISK)':<20} | {'ROI (%)':<8} | {'Vol. Disponibile':<15}\n"
            output_str += "-" * 115 + "\n"

            for _, row in filtered.head(50).iterrows():
                name = str(row['item_name'])[:33]
                buy_p = f"{row['max_buy_price']:,.2f}"
                sell_p = f"{row['min_sell_price']:,.2f}"
                roi_val = f"{row['roi']:.2f}%"
                vol = f"{row['sell_volume_available']:,}"
                output_str += f"{name:<35} | {buy_p:<20} | {sell_p:<20} | {roi_val:<8} | {vol:<15}\n"

            self.txt_output.delete("0.0", "end")
            self.txt_output.insert("0.0", output_str)

        except Exception as e:
            messagebox.showerror("Errore Critico", str(e))
        
        self.btn_fetch.configure(state="normal")

    def get_item_names(self, type_ids):
        names_map = {}
        chunk_size = 500
        for i in range(0, len(type_ids), chunk_size):
            chunk = type_ids[i:i + chunk_size]
            url = f"{ESI_BASE_URL}/universe/names/?datasource=tranquility"
            res = requests.post(url, json=chunk)
            if res.status_code == 200:
                for item in res.json():
                    names_map[item['id']] = item['name']
        return names_map

if __name__ == "__main__":
    app = EveJitaTraderApp()
    app.mainloop()
