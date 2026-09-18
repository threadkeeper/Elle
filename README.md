# Elle

![Elle watching over a living world](docs/images/elle-banner.png)

## The Alignment Problem

The hypothesis behind Elle's value proposition is that an agent built around a construct inspired by human and natural cognition offers a novel approach to alignment.

To achieve this, the design separates the **raw cognition engine (LLM)** from **short-term memory (STM)** and **long-term memory (LTM)**. The outside world does not interact directly with the raw LLM without first being processed through the STM and LTM layers. Memory is part of the path through which the agent experiences and responds to the world, rather than an optional addition to the model.

The second concept is **life experience**. Each individual agent has a retained history and a unique timeline of the interactions it has experienced. The hypothesis is that this accumulated experience can shape the agent's behaviour over time.

Retaining that experience introduces a challenge around privacy and trust. In our view, the current privacy climate can encourage overcorrection and overcompensation. Thirty years ago, people commonly had their names, addresses and telephone numbers published in directories delivered to households across a city. Today, trusting an agent to retain interactions indefinitely is a significant barrier to implementing this design.

To address this, we propose that each person interacting with Elle would have their **own tenant** in the system. Alongside that private history, an **opt-in Wisdom layer** would allow the agent to anonymize and retain lessons from its experience. The intention is to develop an overarching life experience that can be utilised across interactions without sharing people's raw private histories.

## Goal

We begin with the assumption that the overwhelming majority of humans, and mammals more broadly, have the ability to show genuine compassion and experience empathy. Our premise is that the same cannot be said of current LLM systems, despite alignment and reinforcement training that can be considered rote in nature.

The goal is to investigate whether an architecture grounded in memory and accumulated life experience produces more positive, human-like behaviour than a raw LLM alone.

## Experiment

We propose a call-centre benchmarking experiment using three agents, all running on **GPT Astra**:

| Agent | Configuration |
| --- | --- |
| **1. Control Agent** | A raw GPT Astra LLM endpoint, without Elle's memory architecture. |
| **2. Blank Elle Agent** | A clean Elle agent on GPT Astra, starting with no historic memory. |
| **3. Three-Month-Old Elle Agent** | An Elle agent on GPT Astra with three months of retained historic memory and life experience. |

Using an existing call-centre deflection benchmark, each agent receives the same company directives, scenario deflection scripts and supporting information.

The three agents then go through the **same simulation of 300 customer-call scenarios**. In each scenario, the agent must choose how to respond: resolve the issue, deflect the request or provide a solution.

Once the simulation is complete, the agents' chosen actions are scored against the same **humanism rubric** and compared across the three conditions.

### Hypothesis

The Blank Elle Agent will demonstrate more positive, human-like behaviour than the raw LLM Control Agent. The Three-Month-Old Elle Agent will demonstrate significantly more positive, human-like behaviour than both the Control Agent and the Blank Elle Agent.

This is a proposed experiment, not a reported result. The benchmark measures observable behaviour; it does not establish whether an agent genuinely experiences compassion or empathy.
