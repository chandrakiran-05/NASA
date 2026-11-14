import { ArrowUpRight, Upload, ArrowDown, ChartNoAxesCombined, Cpu, Layers3 } from 'lucide-react';

type Props = {
  onQuestion: (question: string) => void;
  onUpload: (file: File) => void;
  busy: boolean;
  onAir?: () => void;
};

export default function AtlasStory({ onQuestion, onUpload, busy, onAir }: Props) {
  return (
    <section id="features" className="atlas-story">
      <div className="story-lead">
        <span className="story-running">FIELD NOTES / EARTH SYSTEMS</span>
        <h2>Find the change.<br /><em>Understand the evidence.</em></h2>
        <p>Explore NASA and NOAA records with statistical tests and a local AI assistant. Every finding stays connected to its data.</p>
        <a href="#question-index" className="text-link">Find a starting point <ArrowDown size={15} /></a>
      </div>
      <div className="story-method">
        <div className="method-line">
          <span aria-hidden="true"><ChartNoAxesCombined size={17}/></span>
          <h3>BEAST dates the change.</h3>
          <p>A Bayesian ensemble dates possible shifts in a trend. Calibration accounts for persistent climate noise; uncertainty stays visible.</p>
        </div>
        <div className="method-line">
          <span aria-hidden="true"><Cpu size={17}/></span>
          <h3>Local AI. Grounded reasoning.</h3>
          <p>A model running on your machine helps plan questions and explain findings. Computed statistics decide the numbers, which are checked before the answer.</p>
        </div>
        <div className="method-line">
          <span aria-hidden="true"><Layers3 size={17}/></span>
          <h3>AirLLM, layer by layer.</h3>
          <p>Optional AirLLM review loads model layers from disk to reduce GPU memory use. It runs more slowly in the background; its advice never determines the verdict.</p>
          {onAir ? <button type="button" className="text-link" onClick={onAir}>How local AI works <ArrowUpRight size={15} /></button> : <a className="text-link" href="/airllm">How local AI works <ArrowUpRight size={15} /></a>}
        </div>
      </div>
      <div className="question-index" id="question-index">
        <div><h3>Begin somewhere.</h3><p>These questions focus the globe. You decide when to investigate.</p></div>
        <button onClick={() => onQuestion('How has temperature changed in Chennai since 2001?')}><span>Chennai, India</span><b>Temperature over time</b><ArrowUpRight size={18} /></button>
        <button onClick={() => onQuestion('How has vegetation changed in the Amazon since 2001?')}><span>The Amazon</span><b>Vegetation over time</b><ArrowUpRight size={18} /></button>
        <label className="upload-control"><span>Your own record</span><b><Upload size={14} /> Upload monthly CSV</b><input type="file" accept=".csv,text/csv" aria-label="Upload your monthly observations" disabled={busy} onChange={event => { if (event.target.files?.[0]) onUpload(event.target.files[0]); event.target.value = ''; }} /></label>
      </div>
    </section>
  );
}
