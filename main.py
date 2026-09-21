<!-- 기존: grid grid-cols-1 md:grid-cols-4 등 -->
<!-- 변경: grid-cols-2 md:grid-cols-4 gap-2 md:gap-4 -->
<div class="grid grid-cols-2 lg:grid-cols-4 gap-2 md:gap-3 my-3">
  <!-- SPX Card -->
  <div class="card p-3 bg-slate-900 border border-slate-800 rounded-lg">
    <div class="text-xs text-slate-400 font-semibold">SPX</div>
    <div class="text-lg md:text-xl font-bold text-emerald-400" id="spx-price">7650.50</div>
    <div class="text-xs text-slate-400" id="spx-change">+0 (0.00%)</div>
  </div>

  <!-- VIX Card -->
  <div class="card p-3 bg-slate-900 border border-slate-800 rounded-lg">
    <div class="flex justify-between items-center">
      <span class="text-xs text-slate-400 font-semibold">VIX</span>
      <span class="text-xs text-emerald-400" id="vix-price">14.81</span>
    </div>
    <div class="flex justify-between items-center mt-1">
      <span class="text-xs text-slate-400">VIX 9D</span>
      <span class="text-xs text-emerald-400" id="vix9d-price">12.27</span>
    </div>
  </div>

  <!-- ES Card -->
  <div class="card p-3 bg-slate-900 border border-slate-800 rounded-lg">
    <div class="flex justify-between items-center">
      <span class="text-xs text-slate-400 font-semibold">ES</span>
      <span class="px-1.5 py-0.5 text-[10px] bg-indigo-900/60 text-indigo-300 rounded">ACTIVE</span>
    </div>
    <div class="text-lg md:text-xl font-bold text-emerald-400" id="es-price">7738.25</div>
    <div class="text-xs text-emerald-400" id="es-change">+0.34%</div>
  </div>

  <!-- MAG7 Card -->
  <div class="card p-3 bg-slate-900 border border-slate-800 rounded-lg">
    <div class="text-xs text-slate-400 font-semibold">MAG7</div>
    <div class="text-lg md:text-xl font-bold text-rose-400" id="mag7-price">70.51</div>
    <div class="text-xs text-rose-400" id="mag7-change">-0.38%</div>
  </div>
</div>
