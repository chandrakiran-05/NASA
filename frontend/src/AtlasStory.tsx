import type React from 'react';
import { ArrowUpRight, ArrowDown } from 'lucide-react';
import './flow3d.css';

/** The project's structure, top to bottom: each layer feeds the next. */
const FLOW = [
  { title: 'Your question, in plain words', tags: ['Planner', 'Everyday words → variables', 'Memory'] },
  { title: 'NASA + NOAA data', tags: ['Giovanni', 'Cloud OPeNDAP', 'ERDDAP', 'NSIDC', 'USGS', 'SWOT'] },
  { title: 'Trend engine', tags: ['Seasons removed', 'Mann-Kendall', 'BEAST + PELT', 'Chance test'] },
  { title: 'Local AI, number-checked', tags: ['Qwen on your GPU', 'Every number verified'] },
  { title: 'Answers you can trust', tags: ['Short answer', 'Full report', 'DigiTwin', 'Discovery'] },
];

type Props = {
  onQuestion: (question: string) => void;
  onAir?: () => void;
};

export default function AtlasStory({ onQuestion, onAir }: Props) {
  return (
    <section id="features" className="atlas-story">
      <div className="story-lead">
        <span className="story-running">FIELD NOTES / EARTH SYSTEMS</span>
        <h2>Find the change.<br /><em>Understand the evidence.</em></h2>
        <p>Explore NASA and NOAA records with statistical tests and a local AI assistant. Every finding stays connected to its data.</p>
        <a href="#question-index" className="text-link">Find a starting point <ArrowDown size={15} /></a>
        <figure className="flow3d" aria-labelledby="flow3d-caption">
          <figcaption id="flow3d-caption" className="story-running">HOW IT FITS TOGETHER</figcaption>
          <ol>
            {FLOW.map((step, i) => (
              <li key={step.title} style={{ '--i': i } as React.CSSProperties}>
                <span className="flow3d-plate" aria-hidden="true"><i>{String(i + 1).padStart(2, '0')}</i></span>
                <div>
                  <b>{step.title}</b>
                  <p>{step.tags.map(t => <span key={t}>{t}</span>)}</p>
                </div>
              </li>
            ))}
          </ol>
        </figure>
      </div>
      <div className="story-method">
        <div className="method-line">
          <span>01</span>
          <h3>BEAST dates the change.</h3>
          <p>A Bayesian ensemble dates possible shifts in a trend. Calibration accounts for persistent climate noise; uncertainty stays visible.</p>
        </div>
        <div className="method-line">
          <span>02</span>
          <h3>Local AI. Grounded reasoning.</h3>
          <p>A model running on your machine helps plan questions and explain findings. Computed statistics decide the numbers, which are checked before the answer.</p>
        </div>
        <div className="method-line">
          <span>03</span>
          <h3>AirLLM, layer by layer.</h3>
          <p>Optional AirLLM review loads model layers from disk to reduce GPU memory use. It runs more slowly in the background; its advice never determines the verdict.</p>
          {onAir ? <button type="button" className="text-link" onClick={onAir}>How local AI works <ArrowUpRight size={15} /></button> : <a className="text-link" href="/airllm">How local AI works <ArrowUpRight size={15} /></a>}
        </div>
      </div>
      <div className="question-index" id="question-index">
        <div><h3>Begin somewhere.</h3><p>These questions focus the globe. You decide when to investigate.</p></div>
        <button onClick={() => onQuestion('How has temperature changed in Chennai since 2001?')}><span>Chennai, India</span><b>Temperature over time</b><ArrowUpRight size={18} /></button>
        <button onClick={() => onQuestion('How has vegetation changed in the Amazon since 2001?')}><span>The Amazon</span><b>Vegetation over time</b><ArrowUpRight size={18} /></button>
      </div>
    </section>
  );
}
