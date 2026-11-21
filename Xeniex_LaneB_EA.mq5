//+------------------------------------------------------------------+
//| Xeniex Lane B EA - Katana v1 + Trend Continuation            |
//| Standalone MT5 Strategy Tester EA. No Python changes required.   |
//+------------------------------------------------------------------+
#property copyright "Xeniex"
#property link      "https://github.com/i0zfnr/goldsignal"
#property version   "1.10"
#property strict

#include <Trade\Trade.mqh>

input group "=== Symbol ==="
input string   InpSymbol            = "";
input long     InpMagic             = 20261122;

input group "=== Risk ==="
input double   InpRiskPercent       = 1.0;
input double   InpMaxSpread         = 0.50;
input double   InpStopBuffer        = 0.10;
input double   InpMinRisk           = 0.50;
input double   InpDefaultRisk       = 2.0;

input group "=== Targets ==="
input double   InpTP1R              = 1.0;
input double   InpTP2R              = 1.5;
input double   InpTP3R              = 2.0;

input group "=== Filters ==="
input bool     InpOnlyAPlus         = true;
input bool     InpUseSessionFilter  = false;
input int      InpSessionStartMin   = 0;
input int      InpSessionEndMin     = 1440;
input bool     InpUseContinuation   = true;

input group "=== Exposure ==="
input int      InpMaxActiveTrades   = 2;
input int      InpMinSpacingMin     = 15;
input double   InpMinDisplacement   = 0.80;

CTrade trade;
string gSymbol;
datetime gLastSignalTime = 0;

struct SwingPoint {
   double price;
   datetime time;
   int index;
   bool isHigh;
};

struct Zone {
   string id;
   int direction;
   double top;
   double bottom;
   datetime created;
   int power;
   datetime expired;
   bool mitigated;
   datetime invalidated;
};

struct Signal {
   string id;
   int direction;
   double entryLow;
   double entryHigh;
   double stopLoss;
   double reference;
   double risk;
   double tp1;
   double tp2;
   double tp3;
   string grade;
   datetime expiry;
};

struct TradeState {
   ulong ticket;
   double entry;
   double risk;
   double tp1;
   double tp2;
   double tp3;
   double lot;
   bool tp1Done;
   bool tp2Done;
};

Zone gZones[];
SwingPoint gSwings[];
Signal gPending;
bool gHasPending = false;
TradeState gStates[];

int OnInit() {
   gSymbol = InpSymbol == "" ? _Symbol : InpSymbol;
   if(!SymbolSelect(gSymbol, true)) {
      Print("Cannot select symbol: ", gSymbol);
      return INIT_FAILED;
   }
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(30);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
}

void OnTick() {
   ExecutePending();

   static datetime lastM15 = 0;
   datetime currentM15 = iTime(gSymbol, PERIOD_M15, 0);
   if(currentM15 != lastM15) {
      lastM15 = currentM15;
      ScanForSetup();
   }

   ManagePositions();
}

int ActiveTradeCount() {
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == gSymbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic) count++;
   }
   return count;
}

bool InSession() {
   if(!InpUseSessionFilter) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int minute = dt.hour * 60 + dt.min;
   return minute >= InpSessionStartMin && minute < InpSessionEndMin;
}

int BiasFromCloses(const double &closes[]) {
   int n = ArraySize(closes);
   if(n < 4) return 0;
   double delta = closes[n - 1] - closes[n - 4];
   if(delta > 0.05) return 1;
   if(delta < -0.05) return -1;
   return 0;
}

int MTFDirection(const double &m15[], const double &m30[], const double &h1[]) {
   int sum = BiasFromCloses(m15) + BiasFromCloses(m30) + BiasFromCloses(h1);
   if(sum >= 2) return 1;
   if(sum <= -2) return -1;
   return 0;
}

double MedianBody(const double &open[], const double &close[], int idx, int window) {
   double bodies[];
   int start = MathMax(0, idx - window);
   for(int i = start; i < idx; i++) {
      int n = ArraySize(bodies);
      ArrayResize(bodies, n + 1);
      bodies[n] = MathAbs(close[i] - open[i]);
   }
   int n = ArraySize(bodies);
   if(n == 0) return 0;
   ArraySort(bodies);
   if(n % 2 == 0) return (bodies[n / 2 - 1] + bodies[n / 2]) / 2.0;
   return bodies[n / 2];
}

void AddZone(const Zone &zone) {
   for(int i = 0; i < ArraySize(gZones); i++) {
      if(gZones[i].direction != zone.direction) continue;
      double overlap = MathMin(gZones[i].top, zone.top) - MathMax(gZones[i].bottom, zone.bottom);
      if(overlap <= 0) continue;
      double minHeight = MathMin(gZones[i].top - gZones[i].bottom, zone.top - zone.bottom);
      if(minHeight > 0 && overlap / minHeight >= 0.4) return;
   }
   int n = ArraySize(gZones);
   ArrayResize(gZones, n + 1);
   gZones[n] = zone;
}

void AddSwing(const SwingPoint &point) {
   int n = ArraySize(gSwings);
   ArrayResize(gSwings, n + 1);
   gSwings[n] = point;
}

void BuildZones(const double &high[], const double &low[], const double &open[],
                const double &close[], const datetime &time[]) {
   ArrayFree(gZones);
   ArrayFree(gSwings);

   int n = ArraySize(high);
   int swingSize = 2;
   for(int i = swingSize; i < n - swingSize; i++) {
      bool isHigh = true;
      bool isLow = true;
      for(int j = i - swingSize; j <= i + swingSize; j++) {
         if(j == i) continue;
         if(high[j] >= high[i]) isHigh = false;
         if(low[j] <= low[i]) isLow = false;
      }
      if(isHigh) {
         SwingPoint point;
         point.price = high[i];
         point.time = time[i];
         point.index = i;
         point.isHigh = true;
         AddSwing(point);
      }
      if(isLow) {
         SwingPoint point;
         point.price = low[i];
         point.time = time[i];
         point.index = i;
         point.isHigh = false;
         AddSwing(point);
      }
   }

   for(int i = 20; i < n - 1; i++) {
      double median = MedianBody(open, close, i, 20);
      double body = MathAbs(close[i] - open[i]);
      if(body < 1.5 * median) continue;

      datetime created = time[i] + 900;
      if(created > TimeCurrent()) continue;

      if(close[i] < open[i]) {
         double broken = 0;
         for(int s = ArraySize(gSwings) - 1; s >= 0; s--) {
            if(gSwings[s].isHigh) continue;
            if(gSwings[s].time + 900 <= time[i] && close[i] < gSwings[s].price && gSwings[s].index < i) {
               broken = gSwings[s].price;
               break;
            }
         }
         if(broken == 0) continue;

         double sourceHigh = 0;
         double sourceLow = 0;
         for(int j = i - 1; j >= MathMax(0, i - 6); j--) {
            if(close[j] > open[j]) {
               sourceHigh = high[j];
               sourceLow = low[j];
               break;
            }
         }
         if(sourceHigh == 0) continue;

         double top = sourceHigh;
         double bottom = sourceLow;
         if(top - bottom > 6.0) {
            double bodyBottom = MathMin(open[i], close[i]);
            bottom = (top - bodyBottom <= 6.0) ? bodyBottom : NormalizeDouble(top - 6.0, _Digits);
         }

         Zone zone;
         zone.id = "z_SELL_" + IntegerToString((long)time[i]);
         zone.direction = -1;
         zone.top = top;
         zone.bottom = bottom;
         zone.created = created;
         zone.power = 8;
         zone.expired = created + 48 * 900;
         zone.mitigated = false;
         zone.invalidated = 0;
         AddZone(zone);
      } else if(close[i] > open[i]) {
         double broken = 0;
         for(int s = ArraySize(gSwings) - 1; s >= 0; s--) {
            if(!gSwings[s].isHigh) continue;
            if(gSwings[s].time + 900 <= time[i] && close[i] > gSwings[s].price && gSwings[s].index < i) {
               broken = gSwings[s].price;
               break;
            }
         }
         if(broken == 0) continue;

         double sourceHigh = 0;
         double sourceLow = 0;
         for(int j = i - 1; j >= MathMax(0, i - 6); j--) {
            if(close[j] < open[j]) {
               sourceHigh = high[j];
               sourceLow = low[j];
               break;
            }
         }
         if(sourceHigh == 0) continue;

         double top = sourceHigh;
         double bottom = sourceLow;
         if(top - bottom > 6.0) {
            double bodyTop = MathMax(open[i], close[i]);
            top = (bodyTop - bottom <= 6.0) ? bodyTop : NormalizeDouble(bottom + 6.0, _Digits);
         }

         Zone zone;
         zone.id = "z_BUY_" + IntegerToString((long)time[i]);
         zone.direction = 1;
         zone.top = top;
         zone.bottom = bottom;
         zone.created = created;
         zone.power = 8;
         zone.expired = created + 48 * 900;
         zone.mitigated = false;
         zone.invalidated = 0;
         AddZone(zone);
      }
   }

   for(int s = 0; s < ArraySize(gSwings); s++) {
      datetime confirmed = gSwings[s].time + 900;
      if(confirmed > TimeCurrent()) continue;
      int idx = gSwings[s].index;
      if(idx < 0 || idx >= n) continue;

      if(!gSwings[s].isHigh) {
         double bottom = NormalizeDouble(gSwings[s].price, _Digits);
         double top = NormalizeDouble(MathMin(bottom + 6.0, MathMax(open[idx], close[idx])), _Digits);
         if(top - bottom < 1.0) top = NormalizeDouble(bottom + 3.0, _Digits);

         Zone zone;
         zone.id = "z_BUY_sw_" + IntegerToString((long)gSwings[s].time);
         zone.direction = 1;
         zone.top = top;
         zone.bottom = bottom;
         zone.created = confirmed;
         zone.power = 8;
         zone.expired = confirmed + 48 * 900;
         zone.mitigated = false;
         zone.invalidated = 0;
         AddZone(zone);
      } else {
         double top = NormalizeDouble(gSwings[s].price, _Digits);
         double bottom = NormalizeDouble(MathMax(top - 6.0, MathMin(open[idx], close[idx])), _Digits);
         if(top - bottom < 1.0) bottom = NormalizeDouble(top - 3.0, _Digits);

         Zone zone;
         zone.id = "z_SELL_sw_" + IntegerToString((long)gSwings[s].time);
         zone.direction = -1;
         zone.top = top;
         zone.bottom = bottom;
         zone.created = confirmed;
         zone.power = 8;
         zone.expired = confirmed + 48 * 900;
         zone.mitigated = false;
         zone.invalidated = 0;
         AddZone(zone);
      }
   }
}

bool ZoneRankLess(const Zone &a, const Zone &b, double price) {
   if(a.mitigated != b.mitigated) return a.mitigated;
   if(a.power != b.power) return a.power > b.power;
   double da = MathAbs(price - (a.top + a.bottom) / 2.0);
   double db = MathAbs(price - (b.top + b.bottom) / 2.0);
   return da > db;
}

void ActiveZones(const Zone &src[], Zone &dst[], double price) {
   ArrayFree(dst);
   Zone temp[];
   for(int i = 0; i < ArraySize(src); i++) {
      if(src[i].expired <= TimeCurrent()) continue;
      if(src[i].invalidated != 0 && src[i].invalidated <= TimeCurrent()) continue;
      int n = ArraySize(temp);
      ArrayResize(temp, n + 1);
      temp[n] = src[i];
   }

   for(int i = 0; i < ArraySize(temp) - 1; i++) {
      for(int j = 0; j < ArraySize(temp) - i - 1; j++) {
         if(ZoneRankLess(temp[j], temp[j + 1], price)) {
            Zone swap = temp[j];
            temp[j] = temp[j + 1];
            temp[j + 1] = swap;
         }
      }
   }

   int sells = 0;
   int buys = 0;
   for(int i = 0; i < ArraySize(temp); i++) {
      if(temp[i].direction == -1 && sells < 3) {
         int n = ArraySize(dst);
         ArrayResize(dst, n + 1);
         dst[n] = temp[i];
         sells++;
      } else if(temp[i].direction == 1 && buys < 3) {
         int n = ArraySize(dst);
         ArrayResize(dst, n + 1);
         dst[n] = temp[i];
         buys++;
      }
      if(sells >= 3 && buys >= 3) break;
   }
}

bool FindM5Rejection(const Zone &zone, const double &high[], const double &low[],
                     const double &open[], const double &close[], const datetime &time[],
                     datetime &rejTime, double &rejHigh, double &rejLow, double &rejClose) {
   for(int i = ArraySize(high) - 1; i >= 0; i--) {
      datetime closeTime = time[i] + 300;
      if(closeTime <= zone.created) break;
      if(closeTime > TimeCurrent()) continue;
      if(high[i] < zone.bottom - 1.0 || low[i] > zone.top + 1.0) continue;

      double range = high[i] - low[i];
      if(zone.direction == -1) {
         double wick = high[i] - MathMax(open[i], close[i]);
         if(close[i] < zone.bottom || (range > 0 && wick / range >= 0.20 && close[i] <= open[i] + 0.5)) {
            rejTime = closeTime;
            rejHigh = high[i];
            rejLow = low[i];
            rejClose = close[i];
            return true;
         }
      } else {
         double wick = MathMin(open[i], close[i]) - low[i];
         if(close[i] > zone.top || (range > 0 && wick / range >= 0.20 && close[i] >= open[i] - 0.5)) {
            rejTime = closeTime;
            rejHigh = high[i];
            rejLow = low[i];
            rejClose = close[i];
            return true;
         }
      }
   }
   return false;
}

bool FindM1Confirmation(int direction, datetime rejTime, double rejHigh, double rejLow,
                        const double &high[], const double &low[], const double &open[],
                        const double &close[], const datetime &time[],
                        datetime &trigTime, double &trigClose) {
   int n = ArraySize(high);
   for(int i = 1; i < n; i++) {
      datetime closeTime = time[i] + 60;
      if(closeTime <= rejTime) continue;
      if(closeTime > TimeCurrent()) break;
      if(closeTime > rejTime + 1800) break;

      double priorLow = low[i - 1];
      double priorHigh = high[i - 1];
      for(int p = i - 2; p >= MathMax(0, i - 3); p--) {
         priorLow = MathMin(priorLow, low[p]);
         priorHigh = MathMax(priorHigh, high[p]);
      }

      if(direction == -1) {
         if(close[i] < priorLow || (close[i] < low[i - 1] && close[i] < open[i])) {
            trigTime = closeTime;
            trigClose = close[i];
            return true;
         }
      } else {
         if(close[i] > priorHigh || (close[i] > high[i - 1] && close[i] > open[i])) {
            trigTime = closeTime;
            trigClose = close[i];
            return true;
         }
      }
   }
   return false;
}

bool BuildCandidate(const Zone &zone, double rejHigh, double rejLow, datetime trigTime,
                    double trigClose, Signal &sig) {
   double ref = trigClose;
   double stop = 0;
   double risk = 0;
   double entryLow = 0;
   double entryHigh = 0;

   if(zone.direction == -1) {
      double naturalHigh = MathMax(rejHigh, zone.top);
      stop = NormalizeDouble(naturalHigh + InpStopBuffer, _Digits);
      risk = NormalizeDouble(stop - ref, _Digits);
      if(risk <= InpMinRisk) {
         risk = InpDefaultRisk;
         stop = NormalizeDouble(ref + risk, _Digits);
      }
      double bandHigh = NormalizeDouble(MathMin(stop - 0.20, MathMax(ref + 0.80, ref + risk * 0.25)), _Digits);
      double bandLow = NormalizeDouble(ref - MathMax(1.20, risk * 0.25), _Digits);
      entryLow = MathMin(bandLow, bandHigh);
      entryHigh = MathMax(bandLow, bandHigh);
      sig.tp1 = NormalizeDouble(ref - risk * InpTP1R, _Digits);
      sig.tp2 = NormalizeDouble(ref - risk * InpTP2R, _Digits);
      sig.tp3 = NormalizeDouble(ref - risk * InpTP3R, _Digits);
   } else {
      double naturalLow = MathMin(rejLow, zone.bottom);
      stop = NormalizeDouble(naturalLow - InpStopBuffer, _Digits);
      risk = NormalizeDouble(ref - stop, _Digits);
      if(risk <= InpMinRisk) {
         risk = InpDefaultRisk;
         stop = NormalizeDouble(ref - risk, _Digits);
      }
      double bandLow = NormalizeDouble(MathMax(stop + 0.20, MathMin(ref - 0.80, ref - risk * 0.25)), _Digits);
      double bandHigh = NormalizeDouble(ref + MathMax(1.20, risk * 0.25), _Digits);
      entryLow = MathMin(bandLow, bandHigh);
      entryHigh = MathMax(bandLow, bandHigh);
      sig.tp1 = NormalizeDouble(ref + risk * InpTP1R, _Digits);
      sig.tp2 = NormalizeDouble(ref + risk * InpTP2R, _Digits);
      sig.tp3 = NormalizeDouble(ref + risk * InpTP3R, _Digits);
   }

   if(entryHigh - entryLow > 4.0) return false;
   if(entryLow <= stop && stop < entryHigh) return false;

   sig.id = "B_" + zone.id + "_" + IntegerToString((long)trigTime);
   sig.direction = zone.direction;
   sig.entryLow = entryLow;
   sig.entryHigh = entryHigh;
   sig.stopLoss = stop;
   sig.reference = ref;
   sig.risk = risk;
   sig.expiry = MathMin(trigTime + 1800, zone.expired);
   return true;
}

string CalculateGrade(bool mtfAligned, const Zone &zone, double rejHigh, double rejLow,
                      double rejClose, double risk, double spread) {
   int score = 0;
   if(mtfAligned) score++;
   if(!zone.mitigated && zone.power >= 8) score++;
   double range = rejHigh - rejLow;
   if(range > 0) {
      double wick = zone.direction == -1 ? rejHigh - rejClose : rejClose - rejLow;
      if(wick / range >= 0.35) score++;
   }
   if(risk <= 2.50 && spread <= 0.40) score++;
   if(score >= 4) return "A+";
   if(score >= 3) return "A";
   if(score >= 2) return "B+";
   return "B";
}

string CalculateContinuationGrade(int direction, int pullbackIdx, const double &open[],
                                  const double &close[], int aligned, double risk, double spread) {
   int score = 0;
   if(aligned >= 2) score++;
   if(pullbackIdx >= 0) {
      double median = 0;
      int count = 0;
      for(int i = MathMax(0, pullbackIdx - 4); i < pullbackIdx; i++) {
         median += MathAbs(close[i] - open[i]);
         count++;
      }
      if(count > 0) median /= count;
      if(median > 0 && MathAbs(close[pullbackIdx] - open[pullbackIdx]) <= median * 0.75) score++;
   }
   if(risk <= 2.50 && spread <= 0.40) score++;
   int total = score + 1;
   if(total >= 4) return "A+";
   if(total >= 3) return "A";
   return "B+";
}

void ScanContinuation(const double &m15[], const double &m30[], const double &h1[],
                      const double &m5High[], const double &m5Low[], const double &m5Open[],
                      const double &m5Close[], const datetime &m5Time[],
                      const double &m1High[], const double &m1Low[], const double &m1Open[],
                      const double &m1Close[], const datetime &m1Time[]) {
   int direction = MTFDirection(m15, m30, h1);
   if(direction == 0) return;
   if(ArraySize(m5Close) < 8 || ArraySize(m1Close) < 5) return;

   int pullback = -1;
   int start = MathMax(2, ArraySize(m5Close) - 13);
   for(int i = ArraySize(m5Close) - 2; i >= start; i--) {
      datetime closeTime = m5Time[i] + 300;
      if(closeTime > TimeCurrent()) continue;
      bool counter = direction == 1 ? m5Close[i] < m5Open[i] : m5Close[i] > m5Open[i];
      if(!counter) continue;

      int sign = direction == 1 ? -1 : 1;
      bool impulse = false;
      for(int p = MathMax(0, i - 3); p < i; p++) {
         if(sign * (m5Close[p] - m5Open[p]) > 0) {
            impulse = true;
            break;
         }
      }
      if(impulse) {
         pullback = i;
         break;
      }
   }
   if(pullback < 0) return;

   datetime rejTime = m5Time[pullback] + 300;
   datetime trigTime = 0;
   double trigClose = 0;
   if(!FindM1Confirmation(direction, rejTime, m5High[pullback], m5Low[pullback],
                          m1High, m1Low, m1Open, m1Close, m1Time, trigTime, trigClose)) return;

   double ref = trigClose;
   double stop = 0;
   double risk = 0;
   double entryLow = 0;
   double entryHigh = 0;

   if(direction == -1) {
      double naturalHigh = MathMax(m5High[pullback], m1High[ArraySize(m1High) - 1]);
      stop = NormalizeDouble(naturalHigh + InpStopBuffer, _Digits);
      risk = NormalizeDouble(stop - ref, _Digits);
      if(risk <= InpMinRisk) {
         risk = InpDefaultRisk;
         stop = NormalizeDouble(ref + risk, _Digits);
      }
      double bandHigh = NormalizeDouble(MathMin(stop - 0.20, MathMax(ref + 0.80, ref + risk * 0.25)), _Digits);
      double bandLow = NormalizeDouble(ref - 0.60, _Digits);
      entryLow = MathMin(bandLow, bandHigh);
      entryHigh = MathMax(bandLow, bandHigh);
   } else {
      double naturalLow = MathMin(m5Low[pullback], m1Low[ArraySize(m1Low) - 1]);
      stop = NormalizeDouble(naturalLow - InpStopBuffer, _Digits);
      risk = NormalizeDouble(ref - stop, _Digits);
      if(risk <= InpMinRisk) {
         risk = InpDefaultRisk;
         stop = NormalizeDouble(ref - risk, _Digits);
      }
      double bandLow = NormalizeDouble(MathMax(stop + 0.20, MathMin(ref - 0.80, ref - risk * 0.25)), _Digits);
      double bandHigh = NormalizeDouble(ref + 0.60, _Digits);
      entryLow = MathMin(bandLow, bandHigh);
      entryHigh = MathMax(bandLow, bandHigh);
   }

   if(entryHigh - entryLow > 4.0) return;
   if(entryLow <= stop && stop < entryHigh) return;

   double spread = (SymbolInfoDouble(gSymbol, SYMBOL_ASK) - SymbolInfoDouble(gSymbol, SYMBOL_BID));
   int aligned = 0;
   if(BiasFromCloses(m15) == direction) aligned++;
   if(BiasFromCloses(m30) == direction) aligned++;
   if(BiasFromCloses(h1) == direction) aligned++;
   string grade = CalculateContinuationGrade(direction, pullback, m5Open, m5Close, aligned, risk, spread);
   if(InpOnlyAPlus && grade != "A" && grade != "A+") return;

   int sign = direction == 1 ? 1 : -1;
   gPending.id = "B_CONT_" + (direction == 1 ? "BUY_" : "SELL_") + IntegerToString((long)trigTime);
   gPending.direction = direction;
   gPending.entryLow = entryLow;
   gPending.entryHigh = entryHigh;
   gPending.stopLoss = stop;
   gPending.reference = ref;
   gPending.risk = risk;
   gPending.tp1 = NormalizeDouble(ref + sign * risk * InpTP1R, _Digits);
   gPending.tp2 = NormalizeDouble(ref + sign * risk * InpTP2R, _Digits);
   gPending.tp3 = NormalizeDouble(ref + sign * risk * InpTP3R, _Digits);
   gPending.grade = grade;
   gPending.expiry = MathMin(trigTime + 1800, TimeCurrent() + 1800);
   gHasPending = true;
   gLastSignalTime = TimeCurrent();
   Print("Continuation signal ", gPending.id, " ", grade);
}

void ScanForSetup() {
   if(gHasPending || !InSession()) return;
   if(ActiveTradeCount() >= InpMaxActiveTrades) return;

   double spread = SymbolInfoDouble(gSymbol, SYMBOL_ASK) - SymbolInfoDouble(gSymbol, SYMBOL_BID);
   if(spread > InpMaxSpread) return;

   double m15High[], m15Low[], m15Open[], m15Close[];
   datetime m15Time[];
   double m30High[], m30Low[], m30Open[], m30Close[];
   double h1High[], h1Low[], h1Open[], h1Close[];
   double m5High[], m5Low[], m5Open[], m5Close[];
   datetime m5Time[];
   double m1High[], m1Low[], m1Open[], m1Close[];
   datetime m1Time[];

   if(CopyHigh(gSymbol, PERIOD_M15, 0, 5000, m15High) < 50) return;
   if(CopyLow(gSymbol, PERIOD_M15, 0, 5000, m15Low) < 50) return;
   if(CopyOpen(gSymbol, PERIOD_M15, 0, 5000, m15Open) < 50) return;
   if(CopyClose(gSymbol, PERIOD_M15, 0, 5000, m15Close) < 50) return;
   if(CopyTime(gSymbol, PERIOD_M15, 0, 5000, m15Time) < 50) return;
   if(CopyHigh(gSymbol, PERIOD_M30, 0, 500, m30High) < 10) return;
   if(CopyLow(gSymbol, PERIOD_M30, 0, 500, m30Low) < 10) return;
   if(CopyOpen(gSymbol, PERIOD_M30, 0, 500, m30Open) < 10) return;
   if(CopyClose(gSymbol, PERIOD_M30, 0, 500, m30Close) < 10) return;
   if(CopyHigh(gSymbol, PERIOD_H1, 0, 500, h1High) < 10) return;
   if(CopyLow(gSymbol, PERIOD_H1, 0, 500, h1Low) < 10) return;
   if(CopyOpen(gSymbol, PERIOD_H1, 0, 500, h1Open) < 10) return;
   if(CopyClose(gSymbol, PERIOD_H1, 0, 500, h1Close) < 10) return;
   if(CopyHigh(gSymbol, PERIOD_M5, 0, 5000, m5High) < 20) return;
   if(CopyLow(gSymbol, PERIOD_M5, 0, 5000, m5Low) < 20) return;
   if(CopyOpen(gSymbol, PERIOD_M5, 0, 5000, m5Open) < 20) return;
   if(CopyClose(gSymbol, PERIOD_M5, 0, 5000, m5Close) < 20) return;
   if(CopyTime(gSymbol, PERIOD_M5, 0, 5000, m5Time) < 20) return;
   if(CopyHigh(gSymbol, PERIOD_M1, 0, 5000, m1High) < 20) return;
   if(CopyLow(gSymbol, PERIOD_M1, 0, 5000, m1Low) < 20) return;
   if(CopyOpen(gSymbol, PERIOD_M1, 0, 5000, m1Open) < 20) return;
   if(CopyClose(gSymbol, PERIOD_M1, 0, 5000, m1Close) < 20) return;
   if(CopyTime(gSymbol, PERIOD_M1, 0, 5000, m1Time) < 20) return;

   BuildZones(m15High, m15Low, m15Open, m15Close, m15Time);

   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   double price = (bid + ask) / 2.0;

   Zone active[];
   ActiveZones(gZones, active, price);
   int primary = MTFDirection(m15Close, m30Close, h1Close);

   for(int i = 0; i < ArraySize(active); i++) {
      datetime rejTime = 0;
      double rejHigh = 0;
      double rejLow = 0;
      double rejClose = 0;
      if(!FindM5Rejection(active[i], m5High, m5Low, m5Open, m5Close, m5Time,
                          rejTime, rejHigh, rejLow, rejClose)) continue;

      datetime trigTime = 0;
      double trigClose = 0;
      if(!FindM1Confirmation(active[i].direction, rejTime, rejHigh, rejLow,
                             m1High, m1Low, m1Open, m1Close, m1Time,
                             trigTime, trigClose)) continue;

      Signal sig;
      if(!BuildCandidate(active[i], rejHigh, rejLow, trigTime, trigClose, sig)) continue;

      string grade = CalculateGrade(primary == active[i].direction, active[i],
                                    rejHigh, rejLow, rejClose, sig.risk, spread);
      if(InpOnlyAPlus && grade != "A" && grade != "A+") continue;
      if(gLastSignalTime > 0 && TimeCurrent() - gLastSignalTime < InpMinSpacingMin * 60) continue;
      if(!CheckDisplacement(sig.direction, price)) continue;

      sig.grade = grade;
      gPending = sig;
      gHasPending = true;
      gLastSignalTime = TimeCurrent();
      Print("Lane B signal ", sig.id, " ", grade);
      return;
   }

   if(InpUseContinuation) {
      ScanContinuation(m15Close, m30Close, h1Close,
                       m5High, m5Low, m5Open, m5Close, m5Time,
                       m1High, m1Low, m1Open, m1Close, m1Time);
   }
}

bool CheckDisplacement(int direction, double price) {
   double anchor = 0;
   datetime latest = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != gSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      int posDirection = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
      if(posDirection != direction) return false;
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(opened > latest) {
         latest = opened;
         anchor = PositionGetDouble(POSITION_PRICE_OPEN);
      }
   }
   if(anchor == 0) return true;
   double moved = direction == 1 ? price - anchor : anchor - price;
   return moved >= InpMinDisplacement;
}

double CalculateLot(double entry, double stop) {
   double riskAmount = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPercent / 100.0;
   double distance = MathAbs(entry - stop);
   if(distance <= 0) return 0;
   double tickValue = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(gSymbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickValue <= 0 || tickSize <= 0) return 0;
   double lossPerLot = distance / tickSize * tickValue;
   if(lossPerLot <= 0) return 0;
   double lot = riskAmount / lossPerLot;
   double step = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_STEP);
   double minLot = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MAX);
   lot = MathFloor(lot / step) * step;
   if(lot < minLot) lot = minLot;
   if(lot > maxLot) lot = maxLot;
   int digits = (int)MathMax(0, -MathLog10(step));
   return NormalizeDouble(lot, digits);
}

ulong FindLatestPosition(datetime since) {
   ulong result = 0;
   datetime newest = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != gSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(opened >= since && opened >= newest) {
         newest = opened;
         result = ticket;
      }
   }
   return result;
}

void StoreState(ulong ticket, Signal &sig, double entry, double lot) {
   int n = ArraySize(gStates);
   ArrayResize(gStates, n + 1);
   gStates[n].ticket = ticket;
   gStates[n].entry = entry;
   gStates[n].risk = sig.risk;
   gStates[n].tp1 = sig.tp1;
   gStates[n].tp2 = sig.tp2;
   gStates[n].tp3 = sig.tp3;
   gStates[n].lot = lot;
   gStates[n].tp1Done = false;
   gStates[n].tp2Done = false;
}

int StateIndex(ulong ticket) {
   for(int i = 0; i < ArraySize(gStates); i++) {
      if(gStates[i].ticket == ticket) return i;
   }
   return -1;
}

void ExecutePending() {
   if(!gHasPending) return;
   if(TimeCurrent() > gPending.expiry) {
      gHasPending = false;
      gPending.id = "";
      return;
   }
   if(ActiveTradeCount() >= InpMaxActiveTrades) return;

   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);
   double spread = ask - bid;
   if(spread > InpMaxSpread) return;

   bool inZone = gPending.direction == 1
      ? (ask >= gPending.entryLow && ask <= gPending.entryHigh)
      : (bid >= gPending.entryLow && bid <= gPending.entryHigh);
   if(!inZone) return;

   double entry = gPending.direction == 1 ? ask : bid;
   double lot = CalculateLot(entry, gPending.stopLoss);
   if(lot <= 0) return;

   datetime before = TimeCurrent();
   bool ok = gPending.direction == 1
      ? trade.Buy(lot, gSymbol, 0.0, gPending.stopLoss, gPending.tp3, "Xeniex Lane B")
      : trade.Sell(lot, gSymbol, 0.0, gPending.stopLoss, gPending.tp3, "Xeniex Lane B");
   if(!ok) {
      Print("Order failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      return;
   }

   ulong ticket = FindLatestPosition(before);
   if(ticket != 0) StoreState(ticket, gPending, entry, lot);
   Print("Order opened: ", gPending.id, " ", gPending.grade, " lot ", lot);
   gHasPending = false;
   gPending.id = "";
}

void ManagePositions() {
   double bid = SymbolInfoDouble(gSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(gSymbol, SYMBOL_ASK);

   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != gSymbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;

      int stateIndex = StateIndex(ticket);
      if(stateIndex < 0) continue;

      int direction = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
      double volume = PositionGetDouble(POSITION_VOLUME);
      double step = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_STEP);
      double minLot = SymbolInfoDouble(gSymbol, SYMBOL_VOLUME_MIN);
      double partial = NormalizeDouble(MathFloor((volume / 3.0) / step) * step,
                                      (int)MathMax(0, -MathLog10(step)));

      if(!gStates[stateIndex].tp1Done) {
         bool hit = direction == 1 ? bid >= gStates[stateIndex].tp1 : ask <= gStates[stateIndex].tp1;
         if(hit) {
            if(partial >= minLot) trade.PositionClosePartial(ticket, partial);
            if(PositionSelectByTicket(ticket)) {
               trade.PositionModify(ticket, gStates[stateIndex].entry, gStates[stateIndex].tp3);
            }
            gStates[stateIndex].tp1Done = true;
         }
      }

      if(gStates[stateIndex].tp1Done && !gStates[stateIndex].tp2Done) {
         bool hit = direction == 1 ? bid >= gStates[stateIndex].tp2 : ask <= gStates[stateIndex].tp2;
         if(hit) {
            if(PositionSelectByTicket(ticket)) {
               double currentVolume = PositionGetDouble(POSITION_VOLUME);
               double closeVolume = NormalizeDouble(MathFloor((currentVolume / 2.0) / step) * step,
                                                    (int)MathMax(0, -MathLog10(step)));
               if(closeVolume >= minLot) trade.PositionClosePartial(ticket, closeVolume);
            }
            if(PositionSelectByTicket(ticket)) {
               trade.PositionModify(ticket, gStates[stateIndex].tp1, gStates[stateIndex].tp3);
            }
            gStates[stateIndex].tp2Done = true;
         }
      }
   }
}
