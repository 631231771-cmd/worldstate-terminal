import type { ProductCountryDetail, ProductEventDetail, ProductEventsResponse, ProductMacroResponse, ProductMarketsResponse, ProductTodayResponse } from "../types/product";
import { request } from "./transport";

export type ProductDataMode = "observed" | "fixture" | "all";

export const productApi = {
  productToday: (dataMode: ProductDataMode = "observed") =>
    request<ProductTodayResponse>(`/v2/product/today?data_mode=${dataMode}`, undefined, [], 45_000),
  productMarkets: (dataMode: ProductDataMode = "observed") =>
    request<ProductMarketsResponse>(`/v2/product/markets?data_mode=${dataMode}`, undefined, [], 45_000),
  productMacro: (dataMode: ProductDataMode = "observed") =>
    request<ProductMacroResponse>(`/v2/product/macro?data_mode=${dataMode}`, undefined, [], 45_000),
  productCountry: (country: string, dimension?: string, dataMode: ProductDataMode = "observed") =>
    request<ProductCountryDetail>(`/v2/product/macro/${encodeURIComponent(country)}?data_mode=${dataMode}${dimension ? `&dimension=${encodeURIComponent(dimension)}` : ""}`, undefined, [], 45_000),
  productEvents: (dataMode: ProductDataMode = "observed", limit = 500) =>
    request<ProductEventsResponse>(`/v2/product/events?data_mode=${dataMode}&limit=${limit}`, undefined, [], 45_000),
  productEvent: (id: string, dataMode: ProductDataMode = "observed") =>
    request<ProductEventDetail>(`/v2/product/events/${encodeURIComponent(id)}?data_mode=${dataMode}`, undefined, [], 45_000),
};
